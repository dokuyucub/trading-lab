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


ACCOUNT_PATH = "/v2/account"
CLOCK_PATH = "/v2/clock"
BARS_PATH = "/v2/stocks/bars"

POISONED_ERROR_BODY = {
    "message": f"request failed for key {CANARIES['api_key']}",
    "account_id": CANARIES["account_id"],
    "equity": CANARIES["equity"],
    "secret": CANARIES["secret"],
    "account_number": CANARIES["account_number"],
}
"""Hata govdesi de sahte sir tasiyor - ve asil onemli olan bu.

Ilk surumde `_poison` yalnizca BASARILI hesap yanitini degistiriyordu;
stub ise her hata icin sabit {"message": "simulated failure"} donuyordu.
Yani "401/403/429/500 yollarinda sizinti yok" testi ARANACAK MALZEME
OLMADAN kosuyordu - bos bir iddiaydi. (Codex, #18 B2.)

Gercek dunyada tam tersi: Alpaca'nin hata govdeleri istegi
yankilayabiliyor, yani sizinti riski en cok hata yolundadir.
"""


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


def test_every_stage_passes_against_the_stub(
    stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    """Dort asama da gercek SDK uzerinden gecmeli.

    Gunluk ve dakikalik ayri asama: eslemeler ayri sozluk girdileri.
    Hic calismayan esleme DAKIKALIK olandi, ve yalnizca gunluge bakan
    bir prob onu goremezdi. (Codex'in #18 kapsam notu.)
    """
    _, state = stub
    _poison(state)
    _future_clock(state)

    assert _run(stub) == 0
    out = capsys.readouterr().out
    assert "OK hesap" in out
    assert "OK borsa saati" in out
    assert "OK gunluk bar" in out
    assert "OK dakikalik bar" in out


def test_the_probe_only_reads_and_only_from_known_paths(
    stub: tuple[str, StubState],
) -> None:
    """Emir gondermez, iptal etmez; yalnizca bilinen yollari okur.

    Metot denetimi tek basina yetmez: bir GET de beklenmeyen bir uca
    gidebilir. Bu yuzden hem metot hem YOL beyaz listeye karsi
    dogrulaniyor.

    Duzeltme notu: PR aciklamasinda "stub yalnizca GET kabul eder"
    demistim, yanlisti - stub POST ve DELETE de destekliyor.
    Dogrulanan sey stub'in kisitlamasi degil, PROBUN davranisi.
    (Codex, #18 B2.)
    """
    _, state = stub
    _poison(state)
    _future_clock(state)
    _run(stub)

    methods = {method for method, _, _ in state.requests}
    assert methods == {"GET"}, f"salt okunur olmayan istek: {methods}"

    allowed = {ACCOUNT_PATH, CLOCK_PATH, BARS_PATH}
    visited = set(state.paths())
    assert visited <= allowed, f"beklenmeyen uc: {sorted(visited - allowed)}"
    assert visited == allowed, f"beklenen uc cagrilmadi: {sorted(allowed - visited)}"


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


@pytest.mark.parametrize("path", [ACCOUNT_PATH, CLOCK_PATH, BARS_PATH])
@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_no_secret_reaches_any_output_on_error_paths(
    stub: tuple[str, StubState],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    path: str,
    status: int,
) -> None:
    """Hata GOVDESI sahte sir tasirken hicbiri ciktiya gecmemeli.

    Hata yollari basari yolundan daha riskli: Alpaca'nin hata
    govdeleri istegi yankilayabiliyor, ve loglar en cok hata aninda
    okunur. Istisna metnini basan bir tani araci tam o anda sizdirir.

    Hata KALICI veriliyor (`times=None`): tek atimlik bir hata, SDK
    yeniden denedigi icin ikinci istekte basariya gecer ve test
    sessizce anlamsizlasir.
    """
    _, state = stub
    _poison(state)
    _future_clock(state)
    state.fail(path, status, times=None, body=POISONED_ERROR_BODY)

    with caplog.at_level(logging.DEBUG):
        assert _run(stub) == 1

    output = _all_output(capsys, caplog)
    leaked = sorted(name for name, value in CANARIES.items() if value in output)
    assert not leaked, f"cikti hassas deger tasiyor: {leaked}\n---\n{output}"


def test_no_secret_reaches_any_output_on_the_success_path(
    stub: tuple[str, StubState],
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, state = stub
    _poison(state)
    _future_clock(state)

    with caplog.at_level(logging.DEBUG):
        assert _run(stub) == 0

    output = _all_output(capsys, caplog)
    assert not [name for name, value in CANARIES.items() if value in output]


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "kimlik dogrulama veya yetki reddi (401)"),
        (403, "kimlik dogrulama veya yetki reddi (403)"),
        (429, "hiz siniri (429)"),
        (500, "sunucu hatasi (500)"),
        (418, "istek reddedildi (418)"),
    ],
)
def test_each_status_gets_its_own_diagnosis(
    stub: tuple[str, StubState],
    capsys: pytest.CaptureFixture[str],
    status: int,
    expected: str,
) -> None:
    """Tani DOGRU sinifi soylemeli - yalnizca "FAIL" demesi yetmez.

    Ilk surumde test sadece "FAIL" ariyordu ve dort durum kodunun
    dordu de ayni yanlis taniyi ("SDK cevrim hatasi") uretiyordu;
    test yine de gecerdi. Artik sinif birebir dogrulaniyor.
    """
    _, state = stub
    _poison(state)
    _future_clock(state)
    state.fail(ACCOUNT_PATH, status, times=None, body=POISONED_ERROR_BODY)

    assert _run(stub) == 1
    out = capsys.readouterr().out
    assert f"FAIL hesap: {expected}" in out
    # Diger asamalar saglikli kalmali: hata TEK asamada.
    assert "OK borsa saati" in out
    assert "OK gunluk bar" in out
    assert "OK dakikalik bar" in out


def test_a_transient_rate_limit_is_retried_and_succeeds(
    stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    """Gecici 429 yeniden denenip gecmeli - kalici olandan farki bu.

    Ikisini ayirmak onemli: gecici sinir "bekle", kalici sinir
    "planini kontrol et" demek.
    """
    _, state = stub
    _poison(state)
    _future_clock(state)
    state.fail(ACCOUNT_PATH, 429, times=1, body=POISONED_ERROR_BODY)

    assert _run(stub) == 0
    assert "OK hesap" in capsys.readouterr().out
    assert state.paths().count(ACCOUNT_PATH) == 2, "yeniden deneme olmadi"


def test_failure_output_carries_no_remote_or_exception_trace(
    stub: tuple[str, StubState], capsys: pytest.CaptureFixture[str]
) -> None:
    _, state = stub
    _poison(state)
    _future_clock(state)
    state.fail(ACCOUNT_PATH, 500, times=None, body=POISONED_ERROR_BODY)

    assert _run(stub) == 1
    out = capsys.readouterr().out
    for trace in ("Traceback", "alpaca.common", "APIError", "{'", '{"'):
        assert trace not in out, f"cikti uzak/istisna izi tasiyor: {trace!r}"


def test_the_transport_has_a_finite_timeout(stub: tuple[str, StubState]) -> None:
    """SDK kendi istegine zaman asimi koymuyor; prob koymali.

    Sessiz bir sunucu karsisinda ilk asama suresiz asilirsa digerleri
    hic kosmaz ve "her asama ayri sonuc verir" ozelligi - aracin
    butun degeri - kaybolur. (Codex, #18 B3.)
    """
    from tlab.execution.alpaca_broker import AlpacaBroker
    from tlab.sdk_compat import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS, bound_transport

    url, _ = stub
    broker = AlpacaBroker("k", "s", paper=True, base_url=url)
    seen: dict[str, Any] = {}
    original = broker._client._session.request

    def spy(method: str, request_url: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return original(method, request_url, **kwargs)

    broker._client._session.request = spy  # type: ignore[assignment]
    bound_transport(broker._client)
    broker.get_account()

    assert seen.get("timeout") == (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
    assert broker._client._retry == 1


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
