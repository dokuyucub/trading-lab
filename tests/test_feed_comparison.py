"""Tarihsel SIP kalite karsilastirmasi: gercek SDK -> yerel taklit sunucu (#17).

Codex kabul sartlari burada OLCULUYOR (AGENTS §11.3):

  * Her bar istegi `feed=sip`, `adjustment=raw` ve baseline araliginda;
    hic IEX ya da baska feed istegi yok. Gercek SDK sayfalamasi (en az
    iki sayfa) ayni sinirlarla izlenir.
  * Erisim kapisi: bar isteginde 401/403 -> `FAIL erisim`, gercek kodla;
    baska feed'e donus yok, ozet yok. Ag, diger HTTP ve SDK donusum
    hatalari `FAIL indirme` olarak AYRI siniflanir.
  * 200 ama bos yanit erisim reddi DEGIL: kalite olcusudur; hepsi bossa
    "kullanilabilir bar dogrulandi" sonucu cikmaz.
  * Kismi sembol sonucu yayimlanmaz; kaynak ve sayim kilitleri; alan
    listesi birebir; sizinti ve log yok. IEX teshisi degismez (kendi
    testleri).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from alpaca_stub import StubState, alpaca_stub
from test_baseline_diagnostic import (
    BASELINE,
    DAYS,
    HOLDOUT,
    MARKERS,
    NOW,
    REPO,
    SYMBOLS,
    full,
    gaps,
    keys_env,
    market,
)
from tlab import baseline_diagnostic, feed_comparison
from tlab.core.calendar import TradingSession
from tlab.core.types import Bar
from tlab.data.dataset import DatasetSpec, canonical_json

BARS = "/v2/stocks/bars"

# --------------------------------------------------------------------------
# Yardimcilar
# --------------------------------------------------------------------------


def task_for(
    tmp_path: Path, status: str = "approved", spec_feed: str = "iex", **changes: Any
) -> Any:
    spec_path = tmp_path / "source.yaml"
    spec_path.write_text(
        f"dataset_id: cmp-source\nstatus: {status}\nsymbols: [SPY, QQQ]\n"
        f"start: {DAYS[0]}\nend: {DAYS[-1]}\nfeed: {spec_feed}\n",
        encoding="utf-8",
    )
    spec = DatasetSpec.from_yaml(spec_path)
    base = replace(
        feed_comparison.SIP_TASK,
        comparison_id="cmp-test",
        source_spec=spec_path,
        source_dataset_id="cmp-source",
        source_spec_sha256=hashlib.sha256(canonical_json(spec.model_dump(mode="json"))).hexdigest(),
        expected_sessions={"calendar": 5, "complete": 5, "baseline": 4, "holdout": 1},
    )
    return replace(base, **changes)


@pytest.fixture
def stub() -> Iterator[tuple[str, StubState]]:
    with alpaca_stub() as running:
        yield running


def compare(stub: tuple[str, StubState], tmp_path: Path, task: Any = None, env: Any = None) -> int:
    url, _ = stub
    return feed_comparison.run(
        env if env is not None else keys_env(),
        NOW,
        out=tmp_path / "out" / "comparison.json",
        task=task if task is not None else task_for(tmp_path),
        base_url=url,
    )


def summary(tmp_path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((tmp_path / "out" / "comparison.json").read_bytes())
    return loaded


def bar_queries(state: StubState) -> list[dict[str, list[str]]]:
    return [
        parse_qs(urlparse(path).query)
        for _, path, _ in state.requests
        if urlparse(path).path == BARS
    ]


def nothing_written(tmp_path: Path) -> bool:
    out = tmp_path / "out"
    return not out.exists() or list(out.iterdir()) == []


def _leaked(text: str) -> list[str]:
    return sorted(name for name, value in MARKERS.items() if value in text)


BODY = {"message": f"{MARKERS['body']} key={MARKERS['api_key']}", "s": MARKERS["secret"]}


# --------------------------------------------------------------------------
# Istek sozlesmesi: yalnizca SIP, yalnizca baseline, sayfalama
# --------------------------------------------------------------------------


def assert_request_contract(query: dict[str, list[str]]) -> None:
    from datetime import datetime

    assert query["feed"] == ["sip"], query
    assert query["adjustment"] == ["raw"], query
    assert datetime.fromisoformat(query["start"][0]) == BASELINE[0].open
    end = datetime.fromisoformat(query["end"][0])
    assert end <= BASELINE[-1].close
    assert end < HOLDOUT[0].open


def test_every_bar_request_is_sip_raw_and_inside_the_baseline(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub
    market(state, noise=True)
    assert compare(stub, tmp_path) == 0

    queries = bar_queries(state)
    assert len(queries) == len(SYMBOLS)
    for query in queries:
        assert_request_contract(query)
    assert {query["symbols"][0] for query in queries} == set(SYMBOLS)
    assert {method for method, _, _ in state.requests} == {"GET"}
    assert set(state.paths()) == {"/v2/calendar", BARS}


def paged(state: StubState, extra: dict[str, list[dict[str, Any]]]) -> None:
    """`state.bars` iki sayfaya bolunur; ikinci sayfaya `extra` eklenir."""
    first: dict[str, list[dict[str, Any]]] = {}
    second: dict[str, list[dict[str, Any]]] = {}
    for symbol, rows in state.bars["bars"].items():
        half = len(rows) // 2
        first[symbol] = rows[:half]
        second[symbol] = rows[half:] + extra.get(symbol, [])
    state.bar_pages = [{"bars": first}, {"bars": second}]


def extra_rows(state: StubState) -> dict[str, list[dict[str, Any]]]:
    """SPY: baseline icinde iki tekrar + holdout gunu ve seans disi saat."""
    spy = state.bars["bars"]["SPY"]
    inside = spy[100:102]
    holdout_day = HOLDOUT[0].day.isoformat()
    outside = [dict(spy[0], t=f"{holdout_day}T15:00:00Z"), dict(spy[0], t=f"{DAYS[0]}T12:00:00Z")]
    return {"SPY": inside + outside}


def test_pagination_is_followed_with_the_same_bounds_and_filter(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Gercek SDK sayfalama dongusu: iki sayfa, ikisinde de ayni sinirlar.
    Ikinci sayfadaki kapsam disi barlar ve tekrarlar, ayni barlarin tek
    sayfada gelmesiyle BIREBIR ayni sonucu verir."""
    _, state = stub
    results = []
    for name in ("tek-sayfa", "iki-sayfa"):
        market(state, gaps)
        extra = extra_rows(state)
        if name == "tek-sayfa":
            state.bar_pages = None
            state.bars["bars"]["SPY"] = state.bars["bars"]["SPY"] + extra["SPY"]
        else:
            paged(state, extra)
        state.requests.clear()
        root = tmp_path / name
        root.mkdir()
        assert compare(stub, root, task_for(root)) == 0
        results.append((capsys.readouterr().out, summary(root)))
        queries = bar_queries(state)
        pages = 2 if name == "iki-sayfa" else 1
        assert len(queries) == pages * len(SYMBOLS)
        for query in queries:
            assert_request_contract(query)
        if name == "iki-sayfa":
            tokens = [query.get("page_token") for query in queries]
            assert tokens == [None, ["page-1"]] * len(SYMBOLS)

    assert results[0] == results[1], "sayfalama sonucu degistirdi"
    assert results[1][1]["symbols"]["SPY"]["duplicate_timestamps"] == 2
    assert results[1][1]["symbols"]["QQQ"]["duplicate_timestamps"] == 0


@pytest.mark.parametrize(
    ("status", "expected"),
    [(500, "FAIL indirme: sunucu hatasi (500)"), (403, "FAIL erisim")],
)
def test_a_second_page_failure_publishes_nothing(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: int,
    expected: str,
) -> None:
    _, state = stub
    market(state)
    paged(state, {})
    state.fail(BARS, status, times=None, after=1, body=BODY)
    assert compare(stub, tmp_path) == 1
    text = capsys.readouterr().out
    assert expected in text and "sembol 1/2" in text
    assert [query.get("page_token") for query in bar_queries(state)] == [None, ["page-1"]]
    assert nothing_written(tmp_path)
    assert not _leaked(text)


# --------------------------------------------------------------------------
# Erisim kapisi ve hata siniflari
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_access_denied_on_the_first_request_stops_with_the_real_code(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    _, state = stub
    market(state)
    state.fail(BARS, status, times=None, body=BODY)
    with caplog.at_level(logging.DEBUG):
        assert compare(stub, tmp_path) == 1
    captured = capsys.readouterr()
    text = captured.out + captured.err + caplog.text

    assert captured.out.startswith(
        f"FAIL erisim: sip tarihsel bar istegi reddedildi (HTTP {status}), sembol 1/2"
    )
    assert "kesin neden belirlenmedi" in captured.out
    other = 403 if status == 401 else 401
    assert f"HTTP {other}" not in text
    assert len(bar_queries(state)) == 1, "reddedilen istekten sonra devam edildi"
    assert all(query["feed"] == ["sip"] for query in bar_queries(state)), "baska feed denendi"
    assert nothing_written(tmp_path)
    assert not _leaked(text), f"hata ciktisi sizdiriyor: {_leaked(text)}"
    assert caplog.text == ""


def test_access_denied_on_a_later_symbol_publishes_no_partial_result(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, state = stub
    market(state)
    state.fail(BARS, 403, times=None, after=1, body=BODY)
    assert compare(stub, tmp_path) == 1
    text = capsys.readouterr().out
    assert "FAIL erisim" in text and "sembol 2/2" in text
    assert [query["symbols"] for query in bar_queries(state)] == [["SPY"], ["QQQ"]]
    assert nothing_written(tmp_path), "kismi sembol sonucu yazildi"


def invalid_bar(state: StubState) -> None:
    rows = state.bars["bars"]["SPY"]
    rows[0] = dict(rows[0], h=rows[0]["l"] - 50)  # high < low: gecersiz OHLC


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("429", "hiz siniri (429)"),
        ("500", "sunucu hatasi (500)"),
        ("422", "istek reddedildi (422)"),
        ("ag", "ag, TLS veya zaman asimi hatasi"),
        ("donusum", "SDK yanitini bizim tipimize cevirirken hata (DataError)"),
    ],
)
def test_other_failures_are_download_failures_not_access(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    case: str,
    expected: str,
) -> None:
    _, state = stub
    market(state)
    if case == "donusum":
        invalid_bar(state)
    else:
        state.fail(BARS, 0 if case == "ag" else int(case), times=None, body=BODY)
    with caplog.at_level(logging.DEBUG):
        assert compare(stub, tmp_path) == 1
    captured = capsys.readouterr()
    text = captured.out + captured.err + caplog.text

    assert captured.out.startswith("FAIL indirme: ")
    assert expected in captured.out
    assert "FAIL erisim" not in text
    assert nothing_written(tmp_path)
    assert not _leaked(text), f"hata ciktisi sizdiriyor: {_leaked(text)}"
    assert "Traceback" not in text


def test_a_calendar_rejection_is_not_an_sip_access_result(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Takvim paper hesaptan gelir; reddi SIP erisimi hakkinda bir sey
    soylemez ve bar istenmez."""
    _, state = stub
    market(state)
    state.fail("/v2/calendar", 403, times=None, body=BODY)
    assert compare(stub, tmp_path) == 1
    text = capsys.readouterr().out
    assert text.startswith("FAIL takvim: ")
    assert "FAIL erisim" not in text
    assert bar_queries(state) == []


# --------------------------------------------------------------------------
# Bos 200: erisim reddi degil, kalite olcusu
# --------------------------------------------------------------------------


def no_spy(symbol: str, index: int, window: TradingSession, bars: list[Bar]) -> list[Bar]:
    return [] if symbol == "SPY" else bars


def test_an_empty_symbol_is_a_quality_result_not_an_access_denial(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, state = stub
    market(state, no_spy)
    assert compare(stub, tmp_path) == 0
    text = capsys.readouterr().out
    result = summary(tmp_path)

    assert "FAIL" not in text
    assert result["access"] == {
        "symbols_requested": 2,
        "symbols_answered": 2,
        "symbols_with_baseline_bars": 1,
    }
    assert result["symbols"]["SPY"]["sessions_without_bars"] == len(BASELINE)
    assert result["verdict"] == "some_ineligible"
    assert "DOGRULANMADI" not in text


def test_all_empty_answers_do_not_claim_usable_bars(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, state = stub
    market(state)
    state.bars = {"bars": {}, "next_page_token": None}
    assert compare(stub, tmp_path) == 0
    text = capsys.readouterr().out
    result = summary(tmp_path)

    assert result["access"]["symbols_answered"] == 2
    assert result["access"]["symbols_with_baseline_bars"] == 0
    assert result["sessions"]["baseline_ineligible"] == len(BASELINE)
    assert "not: hic baseline bari gelmedi; kullanilabilir bar DOGRULANMADI" in text


# --------------------------------------------------------------------------
# Kilitler ve sabit gorev
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "break_source",
    ["dataset_id", "hash", "status", "missing", "spec_feed", "same_feed"],
)
def test_the_source_lock_stops_before_keys_sdk_and_output(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    break_source: str,
) -> None:
    _, state = stub
    market(state)
    if break_source == "dataset_id":
        task = task_for(tmp_path, source_dataset_id="other")
    elif break_source == "hash":
        task = task_for(tmp_path, source_spec_sha256="0" * 64)
    elif break_source == "status":
        task = task_for(tmp_path, status="pilot")
    elif break_source == "missing":
        task = task_for(tmp_path, source_spec=tmp_path / "yok.yaml")
    elif break_source == "spec_feed":
        # Hash tutuyor, ama tanimin kendi feed'i gorevin bildigi degil.
        task = task_for(tmp_path, spec_feed="sip")
    else:
        # Override kaynak feed'iyle ayni: karsilastirma degil.
        task = task_for(tmp_path, feed="iex")
    env = keys_env()

    assert compare(stub, tmp_path, task, env) == 1
    assert capsys.readouterr().out.startswith("FAIL kaynak: ")
    assert env.read == [], f"kaynak kilidinden once ortam okundu: {env.read}"
    assert state.requests == [], "kaynak kilidinden once ag istegi yapildi"
    assert not (tmp_path / "out").exists()


def test_a_session_count_mismatch_stops_before_any_bar_request(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, state = stub
    market(state)
    task = task_for(
        tmp_path, expected_sessions={"calendar": 5, "complete": 5, "baseline": 5, "holdout": 0}
    )
    assert compare(stub, tmp_path, task) == 1
    text = capsys.readouterr().out
    assert "FAIL bolme" in text and "bar istenmedi" in text
    assert set(state.paths()) == {"/v2/calendar"}
    assert nothing_written(tmp_path)


def test_the_sip_task_is_locked_to_the_repo_main_spec_and_the_iex_reference() -> None:
    task = feed_comparison.SIP_TASK
    iex = baseline_diagnostic.TASK
    assert task.comparison_id == "feedcmp-orb-baseline-2026q3-u11-sip-1"
    assert task.source_spec == iex.source_spec == baseline_diagnostic.MAIN_SPEC
    assert task.source_dataset_id == iex.source_dataset_id
    assert task.source_spec_sha256 == iex.source_spec_sha256
    spec = DatasetSpec.from_yaml(REPO / task.source_spec)
    digest = hashlib.sha256(canonical_json(spec.model_dump(mode="json"))).hexdigest()
    assert digest == task.source_spec_sha256
    assert spec.status == "approved"
    assert spec.feed == task.source_feed == "iex"
    assert task.feed == "sip"
    assert dict(task.expected_sessions) == dict(iex.expected_sessions)
    assert dict(task.reference) == {
        "diagnostic_id": iex.diagnostic_id,
        "run_id": 36502365666,
        "artifact_id": 11004953510,
        "artifact_zip_sha256": "5ae3e3e0ab21e3a3bb70d3b6cfe7fadebe506c90f4b200c863fb43711dd7ea98",
    }


def test_the_entry_point_takes_no_task_feed_or_spec(tmp_path: Path) -> None:
    for extra in (["--feed", "iex"], ["--spec", "x.yaml"]):
        with pytest.raises(SystemExit):
            feed_comparison.main(["--out", str(tmp_path / "s.json"), *extra])
    assert not (tmp_path / "s.json").exists()


# --------------------------------------------------------------------------
# Ozet, kapsam, sizinti
# --------------------------------------------------------------------------


def test_the_summary_has_exactly_the_reviewed_fields(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub
    market(state, gaps)
    assert compare(stub, tmp_path) == 0
    result = summary(tmp_path)

    assert set(result) == feed_comparison.SUMMARY_KEYS
    assert set(result["source"]) == feed_comparison.SOURCE_KEYS
    assert set(result["feed_override"]) == feed_comparison.FEED_OVERRIDE_KEYS
    assert set(result["reference"]) == feed_comparison.REFERENCE_KEYS
    assert set(result["access"]) == feed_comparison.ACCESS_KEYS
    assert set(result["producer"]) == baseline_diagnostic.PRODUCER_KEYS
    assert set(result["sessions"]) == feed_comparison.SESSION_KEYS
    assert set(result["policy"]) == feed_comparison.POLICY_KEYS
    for stats in result["symbols"].values():
        assert set(stats) == feed_comparison.SYMBOL_KEYS
    assert result["notes"] == list(feed_comparison.NOTES)
    assert result["kind"] == "baseline-feed-comparison"
    assert result["feed"] == "sip"
    assert result["source"]["spec_feed"] == "iex"
    assert result["feed_override"] == {"source_feed": "iex", "feed": "sip"}
    assert result["reference"]["run_id"] == 36502365666
    assert result["producer"]["commit"] == "c" * 40


def test_quality_counts_match_the_iex_tool_on_the_same_bars(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    """Ikinci algoritma yok: ayni barlarla kalite alanlari IEX teshisiyle
    birebir ayni."""
    from test_baseline_diagnostic import task_for as diagnostic_task

    url, state = stub
    market(state, gaps, noise=True)
    sip_root = tmp_path / "sip"
    sip_root.mkdir()
    assert compare(stub, sip_root, task_for(sip_root)) == 0
    iex_root = tmp_path / "iex"
    iex_root.mkdir()
    code = baseline_diagnostic.run(
        keys_env(),
        NOW,
        out=iex_root / "d.json",
        task=diagnostic_task(iex_root),
        base_url=url,
    )
    assert code == 0
    ours = summary(sip_root)
    theirs = json.loads((iex_root / "d.json").read_bytes())
    for key in (
        "policy",
        "sessions",
        "symbols",
        "ineligible_symbol_sessions",
        "reason_counts",
        "symbols_per_ineligible_session",
        "verdict",
    ):
        assert ours[key] == theirs[key], key


def test_out_of_scope_bars_change_no_output(
    stub: tuple[str, StubState], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, state = stub
    results = []
    for name, noise in (("temiz", False), ("gurultulu", True)):
        market(state, gaps, noise=noise)
        root = tmp_path / name
        root.mkdir()
        assert compare(stub, root, task_for(root)) == 0
        results.append((capsys.readouterr().out, summary(root)))
    assert results[0] == results[1], "kapsam disi barlar ciktiyi degistirdi"


def test_no_marker_date_address_or_log_leaves_the_tool(
    stub: tuple[str, StubState],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, state = stub
    market(state, gaps, noise=True)
    state.broken_header_paths.add(BARS)
    with caplog.at_level(logging.DEBUG):
        assert compare(stub, tmp_path) == 0
    captured = capsys.readouterr()
    text = captured.out + captured.err + (tmp_path / "out" / "comparison.json").read_text()
    assert not _leaked(text), f"sizinti: {_leaked(text)}"
    assert caplog.records == [], "karsilastirma sirasinda log kaydi olustu"
    assert "/v2/" not in text
    for day in DAYS:
        assert day.isoformat() not in text, f"cikti bir gun tasiyor: {day}"
    assert captured.out.startswith(
        "OK karsilastirma cmp-test (kaynak cmp-source; feed iex -> sip, gorev duzeyinde)"
    )


def test_an_existing_summary_is_refused_and_untouched(
    stub: tuple[str, StubState], tmp_path: Path
) -> None:
    _, state = stub
    market(state)
    target = tmp_path / "out" / "comparison.json"
    target.parent.mkdir()
    target.write_text("eski", "utf-8")
    assert compare(stub, tmp_path) == 1
    assert target.read_text("utf-8") == "eski"
    assert state.requests == []


def test_logging_is_restored_after_the_run(stub: tuple[str, StubState], tmp_path: Path) -> None:
    _, state = stub
    market(state, full)
    logging.disable(logging.INFO)
    try:
        assert compare(stub, tmp_path) == 0
        assert logging.root.manager.disable == logging.INFO
    finally:
        logging.disable(logging.NOTSET)
