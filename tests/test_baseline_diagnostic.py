"""Baseline kalite teshisi: gercek SDK -> yerel taklit sunucu (#17).

Codex kabul sartlari burada OLCULUYOR:

  * Kaynak kilidi anahtar, SDK ve cikti dosyasindan ONCE; takvim sayimi
    kilidi bar isteginden ONCE.
  * Her bar istegi [ilk baseline acilisi, son baseline kapanisi] icinde.
  * Kapsam disi barlar (holdout gunleri, seans disi saatler, orada
    tekrarlar) HICBIR ciktiyi degistirmez.
  * Sayim anlamlari: histogram toplami = uygunsuz seans birlesimi,
    agirlikli toplam = uygunsuz sembol-seans; oran OLCUSU ile oran
    GEREKCESI ayri.
  * Sizinti yok, log yok, ozet atomik ve alan listesi birebir.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from alpaca_stub import StubState, alpaca_stub
from test_baseline_job import RecordingEnv
from test_dataset import minute_bars, session, weekdays
from tlab import baseline_diagnostic
from tlab.core.calendar import TradingSession
from tlab.core.types import Bar
from tlab.data.dataset import DatasetSpec, canonical_json

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
DAYS = weekdays(date(2026, 1, 5), 5)
SESSIONS = [session(day) for day in DAYS]
BASELINE, HOLDOUT = SESSIONS[:4], SESSIONS[4:]
SYMBOLS = ("SPY", "QQQ")

MARKERS = {
    "api_key": "DIAGCANARYKEYAAAAAAA",
    "secret": "DIAGCANARYSECRETBBBB",
    "trade_count": "3141593",
    "body": "DIAG-RESPONSE-BODY-CANARY",
}


# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------


def keys_env() -> RecordingEnv:
    return RecordingEnv(
        {
            "ALPACA_PAPER_API_KEY": MARKERS["api_key"],
            "ALPACA_PAPER_SECRET_KEY": MARKERS["secret"],
            "GITHUB_SHA": "c" * 40,
        }
    )


def rows(bars: list[Bar]) -> list[dict[str, Any]]:
    return [
        {
            "t": bar.ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "o": bar.open,
            "h": bar.high,
            "l": bar.low,
            "c": bar.close,
            "v": bar.volume,
            "n": int(MARKERS["trade_count"]),
            "vw": bar.vwap,
        }
        for bar in bars
    ]


Shaper = Callable[[str, int, TradingSession, list[Bar]], list[Bar]]


def full(symbol: str, index: int, window: TradingSession, bars: list[Bar]) -> list[Bar]:
    return bars


def gaps(symbol: str, index: int, window: TradingSession, bars: list[Bar]) -> list[Bar]:
    """QQQ 1. gun acilis 5 dk eksik; SPY 2. gun hic bar yok; 3. gun iki
    sembolde de son 15 dk eksik (kapanis penceresi bos)."""
    if symbol == "QQQ" and index == 0:
        return bars[5:]
    if symbol == "SPY" and index == 1:
        return []
    if index == 2:
        return bars[:-15]
    return bars


def market(state: StubState, shape: Shaper = full, *, noise: bool = False) -> None:
    """Sunucu, istenen araliga BAKMADAN butun donemi dondurur.

    `noise`: kapsam disi barlar - holdout gununde tekrarlar ve acilis
    eksigi, baseline gunlerinde seans disi saatler, donem disi bir gun.
    Bunlarin hicbiri teshis ciktisini degistirmemeli.
    """
    state.calendar = [{"date": day.isoformat(), "open": "09:30", "close": "16:00"} for day in DAYS]
    payload: dict[str, list[dict[str, Any]]] = {}
    for symbol in SYMBOLS:
        bars: list[Bar] = []
        for index, window in enumerate(SESSIONS):
            day = minute_bars(symbol, window)
            if index < len(BASELINE):
                day = shape(symbol, index, window, day)
            elif noise:
                day = day[7:] + day[20:30]
            bars += day
        if noise:
            template = bars[0]
            for window in BASELINE:
                for moment in (window.open - timedelta(hours=2), window.close + timedelta(hours=1)):
                    bars.append(template.model_copy(update={"ts": moment}))
            outside = session(DAYS[-1] + timedelta(days=3))
            bars += minute_bars(symbol, outside)[:30]
        payload[symbol] = rows(bars)
    state.bars = {"bars": payload, "next_page_token": None}


def task_for(tmp_path: Path, status: str = "approved", **changes: Any) -> Any:
    spec_path = tmp_path / "source.yaml"
    spec_path.write_text(
        f"dataset_id: diag-source\nstatus: {status}\nsymbols: [SPY, QQQ]\n"
        f"start: {DAYS[0]}\nend: {DAYS[-1]}\n",
        encoding="utf-8",
    )
    spec = DatasetSpec.from_yaml(spec_path)
    base = replace(
        baseline_diagnostic.TASK,
        diagnostic_id="diag-test",
        source_spec=spec_path,
        source_dataset_id="diag-source",
        source_spec_sha256=hashlib.sha256(canonical_json(spec.model_dump(mode="json"))).hexdigest(),
        expected_sessions={"calendar": 5, "complete": 5, "baseline": 4, "holdout": 1},
    )
    return replace(base, **changes)


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


def diagnose(stub: tuple[str, StubState], tmp_path: Path, task: Any = None, env: Any = None) -> int:
    url, _ = stub
    return baseline_diagnostic.run(
        env if env is not None else keys_env(),
        NOW,
        out=tmp_path / "out" / "diagnostic.json",
        task=task if task is not None else task_for(tmp_path),
        base_url=url,
    )


def summary(tmp_path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((tmp_path / "out" / "diagnostic.json").read_bytes())
    return loaded


def bar_requests(state: StubState) -> list[dict[str, list[str]]]:
    return [
        parse_qs(urlparse(path).query)
        for _, path, _ in state.requests
        if urlparse(path).path == "/v2/stocks/bars"
    ]


# --------------------------------------------------------------------------
# Kilitler
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "break_source",
    ["dataset_id", "hash", "status", "missing"],
)
def test_the_source_lock_stops_before_keys_sdk_and_output(
    stub: tuple[str, StubState], tmp_path: Path, break_source: str
) -> None:
    _, state = stub
    market(state)
    if break_source == "dataset_id":
        task = task_for(tmp_path, source_dataset_id="other")
    elif break_source == "hash":
        task = task_for(tmp_path, source_spec_sha256="0" * 64)
    elif break_source == "status":
        task = task_for(tmp_path, status="pilot")
    else:
        task = task_for(tmp_path, source_spec=tmp_path / "yok.yaml")
    env = keys_env()

    assert diagnose(stub, tmp_path, task, env) == 1
    assert env.read == [], f"kaynak kilidinden once ortam okundu: {env.read}"
    assert state.requests == [], "kaynak kilidinden once ag istegi yapildi"
    assert not (tmp_path / "out").exists()


def test_a_session_count_mismatch_stops_before_any_bar_request(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, state = stub
    market(state)
    task = task_for(
        tmp_path,
        expected_sessions={"calendar": 5, "complete": 5, "baseline": 5, "holdout": 0},
    )
    assert diagnose(stub, tmp_path, task) == 1
    text = capsys.readouterr().out
    assert "FAIL bolme" in text and "bar istenmedi" in text
    assert set(state.paths()) == {"/v2/calendar"}, "sayim tutmadan bar istendi"
    assert not (tmp_path / "out" / "diagnostic.json").exists()


def test_the_task_is_locked_to_the_repo_main_spec() -> None:
    """Sabit gorev depodaki gercek ana tanima kilitli; tanima her dokunus
    teshisi gecersiz kilar."""
    from tlab.baseline_job import MAIN_SPEC

    task = baseline_diagnostic.TASK
    assert task.source_spec == MAIN_SPEC
    spec = DatasetSpec.from_yaml(REPO / task.source_spec)
    assert spec.dataset_id == task.source_dataset_id
    assert spec.status == "approved"
    digest = hashlib.sha256(canonical_json(spec.model_dump(mode="json"))).hexdigest()
    assert digest == task.source_spec_sha256
    assert dict(task.expected_sessions) == {
        "calendar": 63,
        "complete": 63,
        "baseline": 50,
        "holdout": 13,
    }
    assert task.failed_run_id == 36474064587
    assert task.failed_head.startswith("c6c19db")


def test_the_entry_point_takes_no_task_or_spec(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        baseline_diagnostic.main(["--out", str(tmp_path / "s.json"), "--spec", "x.yaml"])
    assert not (tmp_path / "s.json").exists()


# --------------------------------------------------------------------------
# Kapsam: yalnizca baseline
# --------------------------------------------------------------------------


def test_every_bar_request_stays_inside_the_baseline(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub
    market(state, noise=True)
    assert diagnose(stub, tmp_path) == 0

    requests = bar_requests(state)
    assert len(requests) >= len(SYMBOLS)
    for query in requests:
        start = datetime.fromisoformat(query["start"][0])
        end = datetime.fromisoformat(query["end"][0])
        assert start == BASELINE[0].open
        assert end <= BASELINE[-1].close
        assert end < HOLDOUT[0].open
    assert {method for method, _, _ in state.requests} == {"GET"}
    assert set(state.paths()) <= {"/v2/calendar", "/v2/stocks/bars"}


def test_out_of_scope_bars_change_no_output(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Holdout gunu tekrarlari/eksikleri, seans disi saatler ve donem disi
    gun: ozet ve log birebir ayni."""
    _, state = stub
    results = []
    for name, noise in (("temiz", False), ("gurultulu", True)):
        market(state, gaps, noise=noise)
        root = tmp_path / name
        root.mkdir()
        assert diagnose(stub, root, task_for(root)) == 0
        results.append((capsys.readouterr().out, summary(root)))
    assert results[0] == results[1], "kapsam disi barlar ciktiyi degistirdi"


def test_duplicates_are_counted_only_inside_the_baseline(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub

    def baseline_duplicate(
        symbol: str, index: int, window: TradingSession, bars: list[Bar]
    ) -> list[Bar]:
        return bars + bars[100:102] if (symbol, index) == ("SPY", 1) else bars

    market(state, baseline_duplicate, noise=True)
    assert diagnose(stub, tmp_path) == 0
    symbols = summary(tmp_path)["symbols"]
    assert symbols["SPY"]["duplicate_timestamps"] == 2
    assert symbols["QQQ"]["duplicate_timestamps"] == 0, "holdout tekrari sayildi"


# --------------------------------------------------------------------------
# Sayim anlamlari
# --------------------------------------------------------------------------


def test_counts_keep_their_meaning(stub: tuple[str, StubState], tmp_path: Path) -> None:
    _, state = stub
    market(state, gaps)
    assert diagnose(stub, tmp_path) == 0
    result = summary(tmp_path)

    assert result["sessions"] == {
        "calendar": 5,
        "complete": 5,
        "baseline": 4,
        "holdout": 1,
        "baseline_eligible": 1,
        "baseline_ineligible": 3,
    }
    # 3 uygunsuz seans: ikisinde tek sembol, birinde iki sembol.
    assert result["symbols_per_ineligible_session"] == {"1": 2, "2": 1}
    assert result["ineligible_symbol_sessions"] == 4
    histogram = result["symbols_per_ineligible_session"]
    assert sum(histogram.values()) == result["sessions"]["baseline_ineligible"]
    assert (
        sum(int(width) * count for width, count in histogram.items())
        == result["ineligible_symbol_sessions"]
        == sum(item["ineligible_sessions"] for item in result["symbols"].values())
    )
    assert result["reason_counts"] == {
        "seans_ici_bar_yok": 1,
        "acilis_penceresi_eksik": 1,
        "kapanis_penceresinde_bar_yok": 2,
        "eksik_dakika_orani": 0,
        "diger": 0,
    }
    spy, qqq = result["symbols"]["SPY"], result["symbols"]["QQQ"]
    # Bar olmayan seans: oran OLCUSU sinirin ustunde, oran GEREKCESI yok.
    assert spy["sessions_without_bars"] == 1
    assert spy["sessions_missing_fraction_above_limit"] == 1
    assert spy["reason_counts"]["eksik_dakika_orani"] == 0
    assert spy["reason_counts"]["seans_ici_bar_yok"] == 1
    assert qqq["reason_counts"]["acilis_penceresi_eksik"] == 1
    assert qqq["max_missing_open_window"] == 5
    assert qqq["sessions_open_window_incomplete"] == 1
    # Bar olmayan seans acilis OLCUSUNDE de eksik sayilir (pilotla ayni anlam).
    assert spy["sessions_open_window_incomplete"] == 1
    assert result["verdict"] == "some_ineligible"


def test_the_summary_has_exactly_the_reviewed_fields(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub
    market(state, gaps)
    assert diagnose(stub, tmp_path) == 0
    result = summary(tmp_path)

    assert set(result) == baseline_diagnostic.SUMMARY_KEYS
    assert set(result["source"]) == baseline_diagnostic.SOURCE_KEYS
    assert set(result["producer"]) == baseline_diagnostic.PRODUCER_KEYS
    assert set(result["sessions"]) == baseline_diagnostic.SESSION_KEYS
    assert set(result["policy"]) == baseline_diagnostic.POLICY_KEYS
    for stats in result["symbols"].values():
        assert set(stats) == baseline_diagnostic.SYMBOL_KEYS
    assert set(result["symbols_per_ineligible_session"]) == {"1", "2"}
    assert result["notes"] == list(baseline_diagnostic.NOTES)
    assert result["source"]["failed_run_id"] == 36474064587
    assert result["producer"]["commit"] == "c" * 40


# --------------------------------------------------------------------------
# Sizinti, log, hata yollari, atomik ozet
# --------------------------------------------------------------------------


def _leaked(text: str) -> list[str]:
    return sorted(name for name, value in MARKERS.items() if value in text)


def test_no_marker_date_or_log_leaves_the_tool(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, state = stub
    market(state, gaps, noise=True)
    with caplog.at_level(logging.DEBUG):
        assert diagnose(stub, tmp_path) == 0
    captured = capsys.readouterr()
    text = captured.out + captured.err + (tmp_path / "out" / "diagnostic.json").read_text()
    assert not _leaked(text), f"sizinti: {_leaked(text)}"
    assert caplog.text == "", "teshis sirasinda log kaydi gecti"
    for day in DAYS:
        assert day.isoformat() not in text, f"cikti bir gun tasiyor: {day}"
    assert captured.out.startswith("OK teshis diag-test")


@pytest.mark.parametrize("path", ["/v2/stocks/bars", "/v2/calendar"])
@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_errors_are_fixed_and_write_nothing(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    path: str,
    status: int,
) -> None:
    _, state = stub
    market(state)
    body = {"message": f"{MARKERS['body']} key={MARKERS['api_key']}", "s": MARKERS["secret"]}
    state.fail(path, status, times=None, body=body)
    with caplog.at_level(logging.DEBUG):
        assert diagnose(stub, tmp_path) == 1
    captured = capsys.readouterr()
    text = captured.out + captured.err + caplog.text
    assert not _leaked(text), f"hata ciktisi sizdiriyor: {_leaked(text)}\n{text}"
    assert ("FAIL takvim" if path == "/v2/calendar" else "FAIL indirme") in text
    assert not (tmp_path / "out" / "diagnostic.json").exists()
    leftovers = list((tmp_path / "out").iterdir()) if (tmp_path / "out").exists() else []
    assert leftovers == [], f"hata yolunda dosya kaldi: {leftovers}"


def test_an_existing_summary_is_refused_and_untouched(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub
    market(state)
    target = tmp_path / "out" / "diagnostic.json"
    target.parent.mkdir()
    target.write_text("eski", "utf-8")
    env = keys_env()
    assert diagnose(stub, tmp_path, env=env) == 1
    assert target.read_text("utf-8") == "eski"
    assert state.requests == []
