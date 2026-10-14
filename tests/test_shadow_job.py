"""Golge gozlem isi: uctan uca, sahte sunucu ve sanal saatle (tasarim §3, §5, §6).

Gercek alpaca-py istemcisi yerel sahte sunucuya yonlendirilir; saat
sanaldir ve `sleep` onu ilerletir. Bir gunluk gozlem boylece saniyeler
surer. Gosterilenler:

  * tam bir gun: takvim dogrulanir, turlar acilis araliginin sonundan
    giris penceresinin sonuna kadar dakikada bir kosar, SIP son sureye
    kadar beklenir, ozet fiyatsizdir ve calisma dizini silinir;
  * yasak uclara (hesap, pozisyon, emir, dolum) hic istek gitmez;
  * gec baslangic, takvim hatasi, takvimde olmayan gun, veri hatasi,
    eksik anahtar ve plan disi gun sabit sebeplerle yazilir;
  * cikti ve log fiyat, anahtar ya da yanit govdesi tasimaz;
  * gec kayit ve toplam isleri secret'siz calisir.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from alpaca_stub import StubState, alpaca_stub
from conftest import make_bars
from tlab import shadow_job
from tlab.core.clock import SimClock
from tlab.core.types import Timeframe
from tlab.data.market import AlpacaMarketData
from tlab.errors import DataError
from tlab.shadow.summary import DAY_COMPLETE, DAY_INCOMPLETE

DAY = date(2026, 1, 5)
OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
"""Sahte sunucunun takvimindeki gun: 09:30 New York (kis saati)."""
PLANNED = (DAY,)
SYMBOLS = ("SPY", "QQQ")

MARKERS = {
    "api_key": "SHADOWJOBCANARYKEYAA",
    "secret": "SHADOWJOBCANARYSECRET",
    "body": "SHADOW-JOB-BODY-CANARY",
}
ALLOWED = {"/v2/calendar", "/v2/clock", "/v2/stocks/bars", "/v2/stocks/quotes/latest"}
FORBIDDEN = ("/v2/account", "/v2/positions", "/v2/orders")


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as server:
        yield server


@pytest.fixture
def root(project_root: Path) -> Path:
    (project_root / "config" / "universe.yaml").write_text(
        "symbols:\n" + "".join(f"  - {symbol}\n" for symbol in SYMBOLS), encoding="utf-8"
    )
    return project_root


def keys() -> dict[str, str]:
    return {
        "ALPACA_PAPER_API_KEY": MARKERS["api_key"],
        "ALPACA_PAPER_SECRET_KEY": MARKERS["secret"],
    }


def serve_day(state: StubState) -> None:
    """Iki sembol, acilistan 3 saat; SPY 40. dakikada yukari kirar."""
    payload: dict[str, list[dict[str, Any]]] = {}
    for symbol, base in (("SPY", 100.0), ("QQQ", 200.0)):
        bars = make_bars(180, start=OPEN, symbol=symbol, base=base, spread=0.5)
        if symbol == "SPY":
            bars[40] = bars[40].model_copy(
                update={"open": 100.0, "close": 100.8, "high": 100.8, "volume": 30_000.0}
            )
        payload[symbol] = [
            {
                "t": bar.ts.isoformat().replace("+00:00", "Z"),
                "o": bar.open,
                "h": bar.high,
                "l": bar.low,
                "c": bar.close,
                "v": bar.volume,
                "n": bar.trade_count,
                "vw": bar.vwap,
            }
            for bar in bars
        ]
    state.bars = {"bars": payload, "next_page_token": None}


class Sleeper:
    """`sleep` sanal saati ilerletir; toplam bekleme kaydedilir."""

    def __init__(self, clock: SimClock) -> None:
        self.clock = clock
        self.total = 0.0

    def __call__(self, seconds: float) -> None:
        self.total += seconds
        self.clock.set(self.clock.now() + timedelta(seconds=seconds))


def run_observe(
    base_url: str,
    root: Path,
    tmp_path: Path,
    *,
    start: datetime,
    env: dict[str, str] | None = None,
    planned: tuple[date, ...] = PLANNED,
) -> tuple[int, dict[str, Any] | None, SimClock]:
    clock = SimClock(start)
    out = tmp_path / "day.json"
    code = shadow_job.observe(
        keys() if env is None else env,
        clock=clock,
        sleep=Sleeper(clock),
        workdir=tmp_path / "work",
        out=out,
        root=root,
        planned=planned,
        base_url=base_url,
    )
    summary = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return code, summary, clock


def leaked(text: str) -> list[str]:
    return [name for name, marker in MARKERS.items() if marker in text]


def forbidden(state: StubState) -> list[str]:
    return [path for path in state.paths() if path.startswith(FORBIDDEN)]


# --------------------------------------------------------------------------
# Tam gun
# --------------------------------------------------------------------------


def test_a_full_day_is_observed_and_summarised_without_prices(
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    base_url, state = stub
    serve_day(state)
    with caplog.at_level(logging.DEBUG):
        code, summary, clock = run_observe(
            base_url, root, tmp_path, start=OPEN - timedelta(minutes=40)
        )

    assert code == 0
    assert summary is not None
    assert (summary["day"], summary["status"], summary["reason"]) == (
        DAY.isoformat(),
        DAY_COMPLETE,
        None,
    )
    assert summary["turns"] == {"expected": 106, "called": 106, "failed": 0, "missed": 0}
    assert summary["symbol_turns"] == {"expected": 212, "observed": 212}
    by_symbol = {item["symbol"]: item for item in summary["symbols"]}
    assert set(by_symbol) == set(SYMBOLS)
    spy = by_symbol["SPY"]
    assert (spy["iex_present"], spy["window_expected"], spy["sip_available"]) == (15, 15, True)
    assert (spy["or_high_bps"], spy["or_low_bps"]) == (0.0, 0.0)
    assert spy["signal"] == "match"
    assert spy["iex_first_minute"] == pytest.approx(41 + 7 / 60, abs=1e-3)
    assert by_symbol["QQQ"]["signal"] == "none"

    # SIP en erken son turdan 15 dk sonra istendi; son sure asilmadi.
    assert clock.now() >= OPEN + timedelta(minutes=120, seconds=7) + shadow_job.SIP_DELAY
    assert forbidden(state) == []
    assert set(state.paths()) <= ALLOWED
    assert not (tmp_path / "work").exists(), "gecici kayit ve journal silinmeli"

    text = capsys.readouterr().out + caplog.text + json.dumps(summary)
    assert not leaked(text)
    assert caplog.records == [], "is boyunca log kapali olmali"
    for price in ("100.8", "100.5", "99.5", "200.5", "giris"):
        assert price not in text, f"ozet ya da cikti fiyat tasiyor: {price}"


def test_the_summary_carries_only_known_fields(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, state = stub
    serve_day(state)
    _, summary, _ = run_observe(base_url, root, tmp_path, start=OPEN - timedelta(minutes=40))
    assert summary is not None
    assert set(summary) == {
        "day_schema",
        "day",
        "status",
        "reason",
        "params_version",
        "clock_consistent",
        "turns",
        "symbol_turns",
        "sip_reasons",
        "live_pure_mismatches",
        "symbols",
    }
    assert summary["live_pure_mismatches"] == 0


# --------------------------------------------------------------------------
# Eksik gunler ve hata yollari
# --------------------------------------------------------------------------


def test_a_late_start_records_the_day_without_observing(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, state = stub
    serve_day(state)
    code, summary, _ = run_observe(base_url, root, tmp_path, start=OPEN + timedelta(minutes=2))
    assert code == 0
    assert summary is not None
    assert (summary["status"], summary["reason"]) == (DAY_INCOMPLETE, "gec baslangic")
    assert "/v2/stocks/bars" not in state.paths()


def test_a_queue_delay_past_the_open_records_late_without_any_request(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    """Kapi pencerede gecti ama kayit isi kuyrukta acilisi kacirdi: ilk
    denetim ag kullanmadan gunu `eksik (gec baslangic)` yazar."""
    base_url, state = stub
    serve_day(state)
    _, summary, _ = run_observe(base_url, root, tmp_path, start=OPEN - timedelta(seconds=30))
    assert summary is not None
    assert (summary["status"], summary["reason"]) == (DAY_INCOMPLETE, "gec baslangic")
    assert state.requests == []


def test_a_slow_calendar_that_passes_the_open_stops_the_observation(
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ikinci denetim kurulumdan sonra: zaman alan takvim cagrisi acilisi
    kacirttiysa canli gozlem baslamaz."""
    from tlab.execution.alpaca_broker import AlpacaBroker

    base_url, state = stub
    serve_day(state)
    clock = SimClock(OPEN - timedelta(minutes=2))
    original = AlpacaBroker.get_calendar

    def slow(self: AlpacaBroker, *args: Any, **kwargs: Any) -> Any:
        clock.set(clock.now() + timedelta(minutes=3))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AlpacaBroker, "get_calendar", slow)
    out = tmp_path / "day.json"
    code = shadow_job.observe(
        keys(),
        clock=clock,
        sleep=Sleeper(clock),
        workdir=tmp_path / "work",
        out=out,
        root=root,
        planned=PLANNED,
        base_url=base_url,
    )
    assert code == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert (summary["status"], summary["reason"]) == (DAY_INCOMPLETE, "gec baslangic")
    assert "/v2/stocks/bars" not in state.paths()
    assert not (tmp_path / "work").exists()


def test_the_sip_deadline_is_checked_before_every_request(
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Son sure seans saatine bagli tek sabit: yavas istek onu kaydirmaz,
    son sureden sonra istek yapilmaz."""
    from tlab.data.market import AlpacaMarketData

    base_url, state = stub
    serve_day(state)
    clock = SimClock(OPEN - timedelta(minutes=40))
    original = AlpacaMarketData.bars
    sip_calls: list[datetime] = []

    def slow_sip(self: AlpacaMarketData, *args: Any, **kwargs: Any) -> Any:
        if getattr(self, "_feed", None) is not None and str(self._feed).lower().endswith("sip"):
            sip_calls.append(clock.now())
            # Ilk SIP istegi son karar + 15 dk'da; bu istek son sureyi asar.
            clock.set(clock.now() + timedelta(minutes=35))
            return []
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AlpacaMarketData, "bars", slow_sip)
    out = tmp_path / "day.json"
    shadow_job.observe(
        keys(),
        clock=clock,
        sleep=Sleeper(clock),
        workdir=tmp_path / "work",
        out=out,
        root=root,
        planned=PLANNED,
        base_url=base_url,
    )
    summary = json.loads(out.read_text(encoding="utf-8"))
    deadline = OPEN + timedelta(minutes=120) + shadow_job.SIP_DEADLINE
    assert len(sip_calls) == 1, "son sureden sonra ikinci sembol istenmemeli"
    assert all(moment <= deadline for moment in sip_calls)
    assert summary["reason"] == "SIP gelmedi (2 sembol)"
    assert summary["sip_reasons"] == {"QQQ": "son sure doldu", "SPY": "son sure doldu (yanit gec)"}


@pytest.mark.parametrize(
    ("late", "accepted"), [(timedelta(0), True), (timedelta(seconds=1), False)]
)
def test_a_sip_answer_that_returns_after_the_deadline_is_not_accepted(
    late: timedelta,
    accepted: bool,
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Istek son sureden once baslar; tam yanit tam son surede doner
    (kabul) ya da bir saniye sonra doner (red). Gec yanit veri sayilmaz."""
    from tlab.data.market import AlpacaMarketData

    base_url, state = stub
    serve_day(state)
    clock = SimClock(OPEN - timedelta(minutes=40))
    deadline = OPEN + timedelta(minutes=120) + shadow_job.SIP_DEADLINE
    original = AlpacaMarketData.bars
    sip_calls: list[datetime] = []

    def late_sip(self: AlpacaMarketData, *args: Any, **kwargs: Any) -> Any:
        bars = original(self, *args, **kwargs)
        if getattr(self, "_feed", None) is not None and str(self._feed).lower().endswith("sip"):
            sip_calls.append(clock.now())
            if len(sip_calls) == 1:
                clock.set(deadline + late)
        return bars

    monkeypatch.setattr(AlpacaMarketData, "bars", late_sip)
    out = tmp_path / "day.json"
    shadow_job.observe(
        keys(),
        clock=clock,
        sleep=Sleeper(clock),
        workdir=tmp_path / "work",
        out=out,
        root=root,
        planned=PLANNED,
        base_url=base_url,
    )
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert sip_calls[0] < deadline, "istek son sureden once baslamali"
    by_symbol = {item["symbol"]: item for item in summary["symbols"]}
    if accepted:
        assert (summary["status"], summary["reason"]) == (DAY_COMPLETE, None)
        assert summary["sip_reasons"] == {}
        assert by_symbol["SPY"]["sip_available"] is True
        assert by_symbol["SPY"]["or_high_bps"] == 0.0
    else:
        assert summary["reason"] == "SIP gelmedi (2 sembol)"
        assert summary["sip_reasons"] == {
            "QQQ": "son sure doldu",
            "SPY": "son sure doldu (yanit gec)",
        }
        assert len(sip_calls) == 1, "son sureden sonra ikinci istek yapilmamali"
        assert by_symbol["SPY"]["sip_available"] is False
        assert by_symbol["SPY"]["or_high_bps"] is None


def test_a_day_missing_from_the_calendar_is_incomplete(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, state = stub
    holiday = date(2026, 1, 6)
    _, summary, _ = run_observe(
        base_url,
        root,
        tmp_path,
        start=datetime(2026, 1, 6, 13, 50, tzinfo=UTC),
        planned=(holiday,),
    )
    assert summary is not None
    assert (summary["status"], summary["reason"]) == (DAY_INCOMPLETE, "takvimde gun yok")
    assert "/v2/stocks/bars" not in state.paths()


def test_a_calendar_open_that_differs_from_the_regular_open_is_incomplete(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, state = stub
    state.calendar = [{"date": "2026-01-05", "open": "10:30", "close": "16:00"}]
    _, summary, _ = run_observe(base_url, root, tmp_path, start=OPEN - timedelta(minutes=40))
    assert summary is not None
    assert summary["reason"] == "takvim acilisi uyusmuyor"


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_failing_calendar_is_a_fixed_reason_without_leaks(
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    base_url, state = stub
    body = {"message": f"{MARKERS['body']} {MARKERS['api_key']}", "s": MARKERS["secret"]}
    state.fail("/v2/calendar", status, times=None, body=body)
    code, summary, _ = run_observe(base_url, root, tmp_path, start=OPEN - timedelta(minutes=40))
    assert code == 0
    assert summary is not None
    assert summary["status"] == DAY_INCOMPLETE
    assert summary["reason"].startswith("takvim alinamadi: ")
    assert state.paths() == ["/v2/calendar"]
    text = capsys.readouterr().out + json.dumps(summary)
    assert not leaked(text), f"takvim hatasi sizdiriyor: {leaked(text)}"


def test_a_failing_data_endpoint_makes_turns_unknown_and_sip_missing(
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_url, state = stub
    serve_day(state)
    body = {"message": f"{MARKERS['body']} {MARKERS['api_key']}", "s": MARKERS["secret"]}
    state.fail("/v2/stocks/bars", 500, times=None, body=body)
    code, summary, clock = run_observe(base_url, root, tmp_path, start=OPEN - timedelta(minutes=40))
    assert code == 0
    assert summary is not None
    assert summary["status"] == DAY_INCOMPLETE
    assert summary["reason"] == "gozlenemeyen sembol-tur (212/212); SIP gelmedi (2 sembol)"
    for item in summary["symbols"]:
        assert (item["iex_present"], item["iex_unknown_turns"]) == (None, 106)
        assert item["sip_available"] is False
    assert set(summary["sip_reasons"].values()) == {"sunucu hatasi (500)"}
    # SIP son sureye kadar beklendi, sonra birakildi.
    assert clock.now() <= OPEN + timedelta(minutes=120) + shadow_job.SIP_DEADLINE
    assert clock.now() > OPEN + timedelta(minutes=120) + shadow_job.SIP_DEADLINE - (
        shadow_job.SIP_POLL
    )
    assert forbidden(state) == []
    assert not leaked(capsys.readouterr().out + json.dumps(summary))


class LateSleeper(Sleeper):
    """Bir kez fazla uyur: makine yavasladi, dakikalar kacti."""

    def __init__(self, clock: SimClock, at_call: int, extra: float) -> None:
        super().__init__(clock)
        self.calls = 0
        self.at_call = at_call
        self.extra = extra

    def __call__(self, seconds: float) -> None:
        self.calls += 1
        super().__call__(seconds + (self.extra if self.calls == self.at_call else 0.0))


def test_missed_turns_are_not_made_up_and_the_day_is_incomplete(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    """Kacan dakika telafi edilmez; gun `eksik (tur kacti)` olur."""
    base_url, state = stub
    serve_day(state)
    clock = SimClock(OPEN - timedelta(minutes=40))
    out = tmp_path / "day.json"
    code = shadow_job.observe(
        keys(),
        clock=clock,
        sleep=LateSleeper(clock, at_call=10, extra=150.0),
        workdir=tmp_path / "work",
        out=out,
        root=root,
        planned=PLANNED,
        base_url=base_url,
    )
    assert code == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    # 150 sn fazla uyku iki dakikanin turunu kacirir. Kacan turlar sonradan
    # ayni anda kosturulmaz: ne tamamlanan ne de basarisiz tur olarak gorunur.
    assert summary["turns"] == {"expected": 106, "called": 104, "failed": 0, "missed": 2}
    assert summary["symbol_turns"] == {"expected": 212, "observed": 208}
    assert (summary["status"], summary["reason"]) == (
        DAY_INCOMPLETE,
        "tur kacti (2/106); gozlenemeyen sembol-tur (4/212)",
    )


LIVE_BAR_REQUESTS = 106 * len(SYMBOLS)
"""Gozlem boyunca canli bar istegi: tur basina sembol basina bir."""


@pytest.mark.parametrize(
    ("path", "after"),
    [
        ("/v2/stocks/bars", 0),
        ("/v2/stocks/bars", LIVE_BAR_REQUESTS),
        ("/v2/stocks/quotes/latest", 0),
        ("/v2/clock", 0),
        ("/v2/calendar", 0),
    ],
    ids=["live-bars", "sip-bars", "quotes", "clock", "calendar"],
)
def test_no_data_path_leaks_a_body_a_key_or_a_chain(
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    path: str,
    after: int,
) -> None:
    """Yanit govdesi ve istisna zinciri BUTUN gercek veri yollarinda bastirilir.

    Sozlesme deponun gorunurlugunden bagimsizdir (Codex 6154024443).
    Gövde anahtar, secret ve isaret tasir; hicbiri ciktiya, loga ya da
    ozete gecmez.
    """
    base_url, state = stub
    serve_day(state)
    body = {"message": f"{MARKERS['body']} {MARKERS['api_key']}", "s": MARKERS["secret"]}
    state.fail(path, 500, times=None, body=body, after=after)
    with caplog.at_level(logging.DEBUG):
        code, summary, _ = run_observe(base_url, root, tmp_path, start=OPEN - timedelta(minutes=40))
    assert code == 0
    assert summary is not None
    text = capsys.readouterr().out + caplog.text + json.dumps(summary)
    assert not leaked(text), f"{path}: sizinti {leaked(text)}"
    assert "Traceback" not in text
    assert caplog.records == []
    expected_reason = {
        "live-bars": "gozlenemeyen sembol-tur (212/212); SIP gelmedi (2 sembol)",
        "sip-bars": "SIP gelmedi (2 sembol)",
        "quotes": None,
        "clock": None,
        "calendar": "takvim alinamadi: sunucu hatasi (500)",
    }
    key = {
        ("/v2/stocks/bars", 0): "live-bars",
        ("/v2/stocks/bars", LIVE_BAR_REQUESTS): "sip-bars",
        ("/v2/stocks/quotes/latest", 0): "quotes",
        ("/v2/clock", 0): "clock",
        ("/v2/calendar", 0): "calendar",
    }[(path, after)]
    assert summary["reason"] == expected_reason[key]
    if key == "sip-bars":
        assert {item["iex_present"] for item in summary["symbols"]} == {15}
    if key == "clock":
        assert summary["clock_consistent"] is None


def test_a_live_pure_mismatch_marks_the_day(
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canli dongu ile saf yol ayni gorunumden farkli niyet uretirse bu bir
    kod bulgusudur: gun isaretlenir, sessizce `tamam` sayilmaz."""
    import tlab.shadow.core as core

    base_url, state = stub
    serve_day(state)
    monkeypatch.setattr(core, "live_pure_mismatches", lambda *_: 3)
    _, summary, _ = run_observe(base_url, root, tmp_path, start=OPEN - timedelta(minutes=40))
    assert summary is not None
    assert (summary["status"], summary["reason"]) == (
        DAY_INCOMPLETE,
        "canli-saf tutarsizligi (3)",
    )
    assert summary["live_pure_mismatches"] == 3


def test_missing_keys_record_the_day_without_any_request(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, state = stub
    _, summary, _ = run_observe(
        base_url, root, tmp_path, start=OPEN - timedelta(minutes=40), env={}
    )
    assert summary is not None
    assert (summary["status"], summary["reason"]) == (DAY_INCOMPLETE, "yapilandirma")
    assert state.requests == []


def test_an_unplanned_day_does_nothing(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, state = stub
    code, summary, _ = run_observe(
        base_url, root, tmp_path, start=OPEN - timedelta(minutes=40), planned=()
    )
    assert (code, summary) == (0, None)
    assert state.requests == []
    assert not (tmp_path / "work").exists()


def test_an_existing_workdir_is_left_untouched(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, state = stub
    existing = tmp_path / "work"
    existing.mkdir()
    (existing / "keep.txt").write_text("kullanicinin", encoding="utf-8")
    code, summary, _ = run_observe(base_url, root, tmp_path, start=OPEN - timedelta(minutes=40))
    assert (code, summary) == (1, None)
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "kullanicinin"
    assert state.requests == []


def test_the_day_summary_is_never_overwritten(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, _ = stub
    out = tmp_path / "day.json"
    out.write_text("{}", encoding="utf-8")
    code, _, _ = run_observe(base_url, root, tmp_path, start=OPEN + timedelta(minutes=2))
    assert code == 1
    assert out.read_text(encoding="utf-8") == "{}"


def test_the_planned_days_are_empty_until_the_execution_decision() -> None:
    assert shadow_job.PLANNED_DAYS == ()


# --------------------------------------------------------------------------
# Gec kayit ve toplam
# --------------------------------------------------------------------------


def test_the_late_record_writes_an_incomplete_day(tmp_path: Path) -> None:
    out = tmp_path / "day.json"
    code = shadow_job.record_late(
        {}, clock=SimClock(OPEN + timedelta(minutes=20)), out=out, planned=PLANNED
    )
    assert code == 0
    summary = json.loads(out.read_text(encoding="utf-8"))
    assert (summary["status"], summary["reason"]) == (DAY_INCOMPLETE, "gec baslangic")


@pytest.mark.parametrize("step", ["late", "aggregate"])
def test_secret_free_steps_refuse_a_secret_environment(
    step: str, tmp_path: Path, root: Path
) -> None:
    env = {"ALPACA_PAPER_API_KEY": "x"}
    if step == "late":
        code = shadow_job.record_late(
            env, clock=SimClock(OPEN), out=tmp_path / "d.json", planned=PLANNED
        )
    else:
        code = shadow_job.aggregate(
            env, days_dir=tmp_path, out=tmp_path / "t.json", root=root, planned=PLANNED
        )
    assert code == 1


def test_the_aggregate_builds_the_total_from_day_summaries(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    base_url, state = stub
    serve_day(state)
    days = tmp_path / "days"
    days.mkdir()
    run_observe(base_url, root, tmp_path, start=OPEN - timedelta(minutes=40))
    (tmp_path / "day.json").rename(days / "2026-01-05.json")
    second = date(2026, 1, 6)
    shadow_job.record_late(
        {},
        clock=SimClock(datetime(2026, 1, 6, 15, 0, tzinfo=UTC)),
        out=days / "b.json",
        planned=(DAY, second),
    )
    out = tmp_path / "total.json"
    code = shadow_job.aggregate(
        {}, days_dir=days, out=out, root=root, planned=(DAY, second, date(2026, 1, 7))
    )
    assert code == 0
    total = json.loads(out.read_text(encoding="utf-8"))
    assert total["days"] == {"tamam": 1, "eksik": 1, "baslamadi": 0, "bilinmiyor": 1}
    completeness = total["total"]["iex_window_initial"]
    assert (completeness["numerator"], completeness["denominator"]) == (2, 6)
    assert completeness["unknown"] == 4


def test_the_aggregate_refuses_two_summaries_of_one_day(tmp_path: Path, root: Path) -> None:
    days = tmp_path / "days"
    days.mkdir()
    for name in ("a.json", "b.json"):
        shadow_job.record_late(
            {}, clock=SimClock(OPEN + timedelta(minutes=20)), out=days / name, planned=PLANNED
        )
    code = shadow_job.aggregate(
        {}, days_dir=days, out=tmp_path / "t.json", root=root, planned=PLANNED
    )
    assert code == 1
    assert not (tmp_path / "t.json").exists()


# --------------------------------------------------------------------------
# Veri gozlemi, pencere ve SIP butunlugu (Codex 6161518682)
# --------------------------------------------------------------------------


def is_sip(market: AlpacaMarketData) -> bool:
    return str(getattr(market, "_feed", "")).lower().endswith("sip")


class Calls:
    """Canli (IEX) bar cagrilarinin anlari; gercek cagriyi degistirmez."""

    def __init__(self, clock: SimClock, monkeypatch: pytest.MonkeyPatch) -> None:
        self.clock = clock
        self.live: list[datetime] = []
        original = AlpacaMarketData.bars

        def bars(market: AlpacaMarketData, *args: Any, **kwargs: Any) -> Any:
            if not is_sip(market):
                self.live.append(clock.now())
            return original(market, *args, **kwargs)

        monkeypatch.setattr(AlpacaMarketData, "bars", bars)


def observe_with(
    base_url: str, root: Path, tmp_path: Path, clock: SimClock, sleep: Sleeper
) -> dict[str, Any]:
    out = tmp_path / "day.json"
    code = shadow_job.observe(
        keys(),
        clock=clock,
        sleep=sleep,
        workdir=tmp_path / "work",
        out=out,
        root=root,
        planned=PLANNED,
        base_url=base_url,
    )
    assert code == 0
    return dict(json.loads(out.read_text(encoding="utf-8")))


def test_failed_live_data_is_not_a_complete_day(
    stub: tuple[str, StubState], root: Path, tmp_path: Path
) -> None:
    """P2-1: butun canli bar istekleri 403, SIP basarili. Dongu cagrilari
    doner (dongu sembol hatasini yakalar) ama veri gozlenmedi: gun eksik."""
    base_url, state = stub
    serve_day(state)
    state.fail("/v2/stocks/bars", 403, times=LIVE_BAR_REQUESTS)
    summary = observe_with(
        base_url, root, tmp_path, clock := SimClock(OPEN - timedelta(minutes=40)), Sleeper(clock)
    )
    assert (summary["status"], summary["reason"]) == (
        DAY_INCOMPLETE,
        "gozlenemeyen sembol-tur (212/212)",
    )
    assert summary["turns"] == {"expected": 106, "called": 106, "failed": 0, "missed": 0}
    assert summary["symbol_turns"] == {"expected": 212, "observed": 0}
    assert summary["sip_reasons"] == {}
    for item in summary["symbols"]:
        assert (item["range_status"], item["signal"]) == ("bilinmiyor", "unknown")
        assert item["sip_available"] is True


def test_one_lost_symbol_turn_after_the_first_signal_marks_the_day(
    stub: tuple[str, StubState], root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2-1: tek sembolde tek hata, ilk sinyalden (SPY +41) sonra (+60)."""
    base_url, state = stub
    serve_day(state)
    clock = SimClock(OPEN - timedelta(minutes=40))
    lost = OPEN + timedelta(minutes=60)
    original = AlpacaMarketData.bars

    def flaky(market: AlpacaMarketData, symbol: str, *args: Any, **kwargs: Any) -> Any:
        if (
            not is_sip(market)
            and symbol == "SPY"
            and lost <= clock.now() < lost + timedelta(minutes=1)
        ):
            raise DataError("SPY bar verisi alinamadi: gecici")
        return original(market, symbol, *args, **kwargs)

    monkeypatch.setattr(AlpacaMarketData, "bars", flaky)
    summary = observe_with(base_url, root, tmp_path, clock, Sleeper(clock))
    assert (summary["status"], summary["reason"]) == (
        DAY_INCOMPLETE,
        "gozlenemeyen sembol-tur (1/212)",
    )
    assert summary["symbol_turns"] == {"expected": 212, "observed": 211}
    by_symbol = {item["symbol"]: item for item in summary["symbols"]}
    assert (by_symbol["SPY"]["iex_unknown_turns"], by_symbol["SPY"]["signal"]) == (1, "match")
    assert (by_symbol["QQQ"]["iex_unknown_turns"], by_symbol["QQQ"]["signal"]) == (0, "none")


@pytest.mark.parametrize(
    ("at_call", "extra", "called", "last_live"),
    [
        (106, 30.0, 106, OPEN + timedelta(minutes=120, seconds=37)),  # son dakika icinde
        (106, 60.0, 105, OPEN + timedelta(minutes=119, seconds=7)),  # +121:07'ye tasar
        (106, 120.0, 105, OPEN + timedelta(minutes=119, seconds=7)),  # +122:07'ye tasar
        (1, 7200.0, 0, None),  # ilk uyku pencerenin tamamini asar
    ],
    ids=["son-dakika-icinde", "121-e-tasar", "122-ye-tasar", "ilk-uyku-pencereyi-asar"],
)
def test_a_turn_never_runs_after_its_minute(
    at_call: int,
    extra: float,
    called: int,
    last_live: datetime | None,
    stub: tuple[str, StubState],
    root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2-2: uykudan sonra gercek saat denetlenir. Dakikasi gecen tur
    kosmaz ve telafi edilmez; pencere disinda canli istek yapilmaz."""
    base_url, state = stub
    serve_day(state)
    clock = SimClock(OPEN - timedelta(minutes=40))
    calls = Calls(clock, monkeypatch)
    summary = observe_with(
        base_url, root, tmp_path, clock, LateSleeper(clock, at_call=at_call, extra=extra)
    )
    missed = 106 - called
    assert summary["turns"] == {"expected": 106, "called": called, "failed": 0, "missed": missed}
    assert summary["symbol_turns"] == {"expected": 212, "observed": 2 * called}
    assert len(calls.live) == 2 * called
    assert all(moment < OPEN + timedelta(minutes=121) for moment in calls.live)
    assert (max(calls.live) if calls.live else None) == last_live
    if missed:
        assert summary["status"] == DAY_INCOMPLETE
        assert summary["reason"] == (
            f"tur kacti ({missed}/106); gozlenemeyen sembol-tur ({2 * missed}/212)"
        )
    else:
        assert (summary["status"], summary["reason"]) == (DAY_COMPLETE, None)


def test_a_failing_turn_is_counted_apart_and_marks_the_day(
    stub: tuple[str, StubState], root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hata atan dongu cagrisi ne donen ne kacan sayilir; gun eksik."""
    from tlab.engine.runner import SessionRunner

    base_url, state = stub
    serve_day(state)
    clock = SimClock(OPEN - timedelta(minutes=40))
    broken = OPEN + timedelta(minutes=50)
    original = SessionRunner.run_once

    def run_once(runner: SessionRunner) -> Any:
        if broken <= clock.now() < broken + timedelta(minutes=1):
            raise RuntimeError("tur hatasi")
        return original(runner)

    monkeypatch.setattr(SessionRunner, "run_once", run_once)
    summary = observe_with(base_url, root, tmp_path, clock, Sleeper(clock))
    assert summary["turns"] == {"expected": 106, "called": 105, "failed": 1, "missed": 0}
    assert summary["symbol_turns"] == {"expected": 212, "observed": 210}
    assert (summary["status"], summary["reason"]) == (
        DAY_INCOMPLETE,
        "tur hatali (1/106); gozlenemeyen sembol-tur (2/212)",
    )


class FakeSip:
    """Saf SIP saglayicisi: her cagrida siradaki yaniti dondurur (son yanit tekrarlanir)."""

    def __init__(self, clock: SimClock, responses: list[list[Any]]) -> None:
        self.clock = clock
        self.responses = responses
        self.calls: list[datetime] = []

    def bars(self, symbol: str, timeframe: Any, start: datetime, end: datetime) -> list[Any]:
        self.calls.append(self.clock.now())
        return list(self.responses[min(len(self.calls), len(self.responses)) - 1])


SIP_END = OPEN + timedelta(minutes=120, seconds=7)
"""Son turun ani: acilistan 0 ... 119. dakikalarin barlari kapanmis olmali."""
SIP_DEADLINE_AT = OPEN + timedelta(minutes=120) + shadow_job.SIP_DEADLINE


def fetch_sip(responses: list[list[Any]]) -> tuple[dict[str, Any], dict[str, str], FakeSip]:
    clock = SimClock(SIP_END + shadow_job.SIP_DELAY)
    provider = FakeSip(clock, responses)
    complete, reasons = shadow_job._fetch_sip(
        provider,
        ["SPY"],
        Timeframe.M1,
        start=OPEN - timedelta(days=3),
        end=SIP_END,
        session_open=OPEN,
        clock=clock,
        sleep=Sleeper(clock),
        deadline=SIP_DEADLINE_AT,
    )
    return complete, reasons, provider


def day_bars(*, without: tuple[int, ...] = ()) -> list[Any]:
    bars = make_bars(130, start=OPEN, symbol="SPY")
    return [bar for bar in bars if (bar.ts - OPEN) // timedelta(minutes=1) not in without]


@pytest.mark.parametrize(
    ("response", "missing"),
    [
        ([make_bars(1, start=OPEN + timedelta(minutes=119), symbol="SPY")[0]], 119),
        (day_bars(without=(7,)), 1),
        (day_bars(without=(60, 61)), 2),
    ],
    ids=["yalniz-kuyruk-bari", "acilis-penceresinde-eksik", "ortada-eksik"],
)
def test_an_incomplete_sip_answer_is_never_complete(response: list[Any], missing: int) -> None:
    """P2-3: son barin varligi yetmez; eksik yanit son sureye kadar yeniden
    istenir ve son surede hala eksikse SIP yoktur."""
    complete, reasons, provider = fetch_sip([response])
    assert complete == {}
    assert reasons == {"SPY": f"yanit eksik ({missing} dakika)"}
    # Son sureye kadar bes dakikada bir: 135:07 ... 160:07; son sureden sonra istek yok.
    assert len(provider.calls) == 6
    assert all(moment <= SIP_DEADLINE_AT for moment in provider.calls)


def test_an_answer_completed_on_a_later_request_is_accepted() -> None:
    complete, reasons, provider = fetch_sip([day_bars(without=(60,)), day_bars()])
    assert set(complete) == {"SPY"}
    assert reasons == {}
    assert len(provider.calls) == 2


def test_a_complete_answer_is_accepted_at_once() -> None:
    complete, reasons, provider = fetch_sip([day_bars()])
    assert (set(complete), reasons, len(provider.calls)) == ({"SPY"}, {}, 1)


def test_an_incomplete_sip_reaches_the_day_and_the_total_as_unknown(
    stub: tuple[str, StubState], root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2-3 uctan uca: SPY'nin SIP yanitinda ortada bir dakika eksik. Gun
    ozeti SPY icin SIP'i yok sayar; toplamda aralik ve niyet `unknown`."""
    base_url, state = stub
    serve_day(state)
    clock = SimClock(OPEN - timedelta(minutes=40))
    original = AlpacaMarketData.bars
    gap = OPEN + timedelta(minutes=60)

    def holed(market: AlpacaMarketData, symbol: str, *args: Any, **kwargs: Any) -> Any:
        bars = original(market, symbol, *args, **kwargs)
        if is_sip(market) and symbol == "SPY":
            return [bar for bar in bars if bar.ts != gap]
        return bars

    monkeypatch.setattr(AlpacaMarketData, "bars", holed)
    summary = observe_with(base_url, root, tmp_path, clock, Sleeper(clock))
    assert (summary["status"], summary["reason"]) == (DAY_INCOMPLETE, "SIP gelmedi (1 sembol)")
    assert summary["sip_reasons"] == {"SPY": "yanit eksik (1 dakika)"}
    by_symbol = {item["symbol"]: item for item in summary["symbols"]}
    spy = by_symbol["SPY"]
    assert (spy["sip_available"], spy["range_status"], spy["signal"]) == (
        False,
        "sip_yok",
        "unknown",
    )
    assert by_symbol["QQQ"]["sip_available"] is True

    days = tmp_path / "days"
    days.mkdir()
    (tmp_path / "day.json").rename(days / f"{DAY.isoformat()}.json")
    out = tmp_path / "total.json"
    assert shadow_job.aggregate({}, days_dir=days, out=out, root=root, planned=PLANNED) == 0
    total = json.loads(out.read_text(encoding="utf-8"))["total"]
    assert (total["range_within_bps"]["denominator"], total["range_within_bps"]["unknown"]) == (
        2,
        1,
    )
    assert total["intent_agreement"]["unknown"] == 1
