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
    assert summary["turns"] == {"expected": 106, "completed": 106, "failed": 0}
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
    assert summary["reason"] == "SIP gelmedi (2 sembol)"
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
    assert summary["turns"] == {"expected": 106, "completed": 104, "failed": 0}
    assert (summary["status"], summary["reason"]) == (DAY_INCOMPLETE, "tur kacti (2/106)")


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
        "live-bars": "SIP gelmedi (2 sembol)",
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
