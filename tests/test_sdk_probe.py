"""SDK probu: gercek adaptorlerimizi yerel taklit sunucuya karsi surer.

Iki soruyu ayri ayri cevapliyor:

1. Bizim kodumuz gercek SDK uzerinden Alpaca'nin yanit sekillerini
   dogru okuyor mu? (`tlab fetch`'i hic calismaz hale getiren
   Timeframe hatasi tam bu bosluktan kacmisti.)

2. Prob hicbir kosulda hassas deger sizdiriyor mu?

Ikincisinin yontemi Codex'in onerisi (#17) ve benim ilk fikrimden
iyi: ben "hassas alanlar yalnizca su dosyalarda basilabilir" seklinde
bir AST kapisi onermistim; o yaklasim takma adli ve dinamik loglari
kacirir, ustelik piyasa sayilarini yanlislikla isaretler.

Bunun yerine sunucunun yanitlarina SAHTE SIR ISARETLERI konuyor ve
probun butun ciktisi (stdout + stderr + logging) yakalanip bu
isaretlerin hicbirinin gecmedigi dogrulaniyor. Kaynak kodu
incelemek CIKARIM yapar; bu test BILIR.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from alpaca_stub import StubState, alpaca_stub, bar_payload
from tlab import sdk_probe

NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)

CANARIES = {
    "api_key": "CANARYKEYAAAAAAAAAAA",
    "secret": "CANARYSECRETBBBBBBBB",
    "account_number": "CANARYACCT99999",
    "equity": "31415926.53",
    "account_id": "caaa2a2a-0000-4000-8000-cccccccccccc",
}
"""Sunucunun yanitlarina konan sahte sirlar.

Hicbiri gercek degil; isleri ciktida ARANMAK. Biri gorunurse prob
sizdiriyor demektir.
"""


def _poison(state: StubState) -> None:
    """Yanitlari sahte sirlarla doldurur - basari ve hata yollarinda."""
    state.account.update(
        {
            "account_number": CANARIES["account_number"],
            "id": CANARIES["account_id"],
            "equity": CANARIES["equity"],
            "last_equity": CANARIES["equity"],
            "cash": CANARIES["equity"],
            "buying_power": CANARIES["equity"],
        }
    )
    state.clock = dict(state.clock)
    state.bars = bar_payload(
        "SPY",
        [
            {
                "t": (NOW - timedelta(days=day)).isoformat().replace("+00:00", "Z"),
                "o": 500.0,
                "h": 501.0,
                "l": 499.0,
                "c": 500.5,
                "v": 1_000_000,
                "n": 900,
                "vw": 500.2,
            }
            for day in (3, 2, 1)
        ],
    )


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


def _future_clock(state: StubState) -> None:
    """Saat degerlerini gelecege tasi.

    Sabit taklit veri eskir; prob gecmisteki bir `next_open` degerini
    hakli olarak reddeder. Testin olcmek istedigi sey bu degil.
    """
    state.clock = dict(state.clock)
    state.clock["next_open"] = (NOW + timedelta(hours=18)).isoformat().replace("+00:00", "Z")
    state.clock["next_close"] = (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    state.clock["is_open"] = True


def _run(stub: tuple[str, StubState], **kwargs: Any) -> int:
    url, _ = stub
    return sdk_probe.run(CANARIES["api_key"], CANARIES["secret"], NOW, base_url=url, **kwargs)


# --------------------------------------------------------------------------
# Gercek SDK yolu
# --------------------------------------------------------------------------


def test_all_three_stages_pass_against_the_stub(
    stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    """Uc asama da gercek SDK uzerinden gecmeli."""
    _, state = stub
    _poison(state)
    _future_clock(state)

    assert _run(stub) == 0
    out = capsys.readouterr().out
    assert "OK hesap" in out
    assert "OK borsa saati" in out
    assert "OK bar verisi" in out


def test_the_probe_only_reads(stub: tuple[str, StubState]) -> None:
    """Emir gondermez, iptal etmez, pozisyon kapatmaz."""
    _, state = stub
    _poison(state)
    _future_clock(state)
    _run(stub)

    methods = {method for method, _, _ in state.requests}
    assert methods == {"GET"}, f"salt okunur olmayan istek: {methods}"


def test_an_open_session_is_not_rejected(
    stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    """Borsa ACIKKEN `next_close < next_open` normaldir.

    Kolayca yapilan bir hata: kosulsuz `next_open < next_close`
    kurali koymak. Seans aciksa bir sonraki kapanis bugun, bir
    sonraki acilis yarindir - yani sira terstir ve dogrudur. Boyle bir
    kural, borsa her acik oldugunda kosuyu kirardi.

    (Codex'in #17'deki uyarisi; bu test onun karsiligi.)
    """
    _, state = stub
    _poison(state)
    _future_clock(state)
    assert state.clock["next_close"] < state.clock["next_open"]

    _run(stub)
    assert "OK borsa saati" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Sizinti - bu dosyanin asil sebebi
# --------------------------------------------------------------------------


def _all_output(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err + caplog.text


@pytest.mark.parametrize("status", [200, 401, 403, 429, 500])
def test_no_secret_reaches_any_output_stream(
    stub: tuple[str, StubState],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    """Basari ve hata yollarinin HICBIRINDE sahte sir gorunmemeli.

    Hata yollari ozellikle onemli: Alpaca'nin hata govdeleri istegi
    yankilayabiliyor ve orada anahtar bulunabilir. Istisna metnini
    basan bir tani araci, hata aninda - yani en cok log okunan anda -
    sizdirir.
    """
    _, state = stub
    _poison(state)
    _future_clock(state)
    if status != 200:
        state.fail_next = status

    with caplog.at_level(logging.DEBUG):
        _run(stub)

    output = _all_output(capsys, caplog)
    leaked = sorted(name for name, value in CANARIES.items() if value in output)
    assert not leaked, f"cikti hassas deger tasiyor: {leaked}\n---\n{output}"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_failures_are_classified_not_echoed(
    stub: tuple[str, StubState],
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    """Hata sabit bir taniya cevrilmeli, uzak metin yankilanmamali."""
    _, state = stub
    _poison(state)
    state.fail_next = status

    assert _run(stub) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    # Uzak govdeden gelebilecek izler cikmamali.
    for trace in ("Traceback", "alpaca.common", "APIError", "{'", '{"'):
        assert trace not in out, f"cikti uzak/istisna izi tasiyor: {trace!r}"


# --------------------------------------------------------------------------
# Yapilandirma kapisi
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "secret", "fragment"),
    [
        ("", "s", "gerekli"),
        ("k", "", "gerekli"),
        ("   ", "s", "gerekli"),
        ("k\ne", "s", "gecersiz karakter"),
        ("k e", "s", "gecersiz karakter"),
        ("kÇ", "s", "gecersiz karakter"),
    ],
)
def test_bad_credentials_fail_before_any_request(
    stub: tuple[str, StubState],
    capsys: pytest.CaptureFixture[str],
    key: str,
    secret: str,
    fragment: str,
) -> None:
    """Bozuk anahtar ag'a cikmadan, NET bir mesajla durmali.

    `paper_probe`'da yasanan ders: kirpilmamis bir anahtar "ag hatasi"
    gibi gorunuyordu ve bizi olmayan bir ag sorununu aramaya
    gonderiyordu. Ayni tuzak burada tekrarlanmasin.
    """
    url, state = stub
    assert sdk_probe.run(key, secret, NOW, base_url=url) == 1
    assert fragment in capsys.readouterr().out
    assert not state.requests, "gecersiz anahtarla ag istegi yapildi"


def test_naive_time_is_rejected(
    stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    url, _ = stub
    assert sdk_probe.run("k", "s", datetime(2026, 9, 24, 15, 0), base_url=url) == 1
    assert "zaman dilimi" in capsys.readouterr().out
