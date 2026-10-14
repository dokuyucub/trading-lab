"""Golge gozlem ozeti (docs/designs/shadow-observation.md §4).

Gosterilenler: planli her gun ve sembol-gun paydada kalir; unknown iki
yone de sayilarak karara baglanir; asgari destek yoksa sonuc belirsiz;
iki tarafta niyet yoklugu uyum sayilmaz; ozet fiyat tasimaz.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from tlab.shadow.core import (
    RANGE_COMPUTED,
    RANGE_IEX_INCOMPLETE,
    RANGE_INVALID,
    RANGE_SIP_INCOMPLETE,
    RANGE_SIP_MISSING,
    RANGE_UNKNOWN,
    SIGNAL_MATCH,
    SIGNAL_MISMATCH,
    SIGNAL_NONE,
    SIGNAL_UNKNOWN,
    Comparison,
)
from tlab.shadow.summary import (
    DAY_COMPLETE,
    DAY_INCOMPLETE,
    DAY_NOT_STARTED,
    DAY_UNKNOWN,
    FAILED,
    INCONCLUSIVE,
    PASSED,
    Day,
    Rate,
    SymbolDay,
    Thresholds,
    summarize,
)

SYMBOLS = ("SPY", "QQQ")
PLANNED = [date(2026, 11, 2) + timedelta(days=offset) for offset in range(4)]
THRESHOLDS = Thresholds(range_min_support=2, intent_min_support=2, intent_min_days=2)

GOOD = Comparison(
    symbol="SPY",
    window_expected=15,
    iex_present=15,
    sip_present=15,
    iex_completed_later=False,
    or_high_bps=1.5,
    or_low_bps=-0.5,
    range_status=RANGE_COMPUTED,
    signal=SIGNAL_MATCH,
    iex_first_minute=30.1,
    sip_first_minute=30.1,
    iex_unknown_turns=0,
)


def result(
    day: date, symbol: str, comparison: Comparison | None = GOOD, *, sip: bool = True
) -> SymbolDay:
    if comparison is not None:
        comparison = replace(comparison, symbol=symbol)
    return SymbolDay(day=day, symbol=symbol, comparison=comparison, sip_available=sip)


def every(comparison: Comparison | None = GOOD, *, sip: bool = True) -> list[SymbolDay]:
    return [result(day, symbol, comparison, sip=sip) for day in PLANNED for symbol in SYMBOLS]


def complete_days() -> list[Day]:
    return [Day(day, DAY_COMPLETE) for day in PLANNED]


# --------------------------------------------------------------------------
# Karar kurali
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("numerator", "unknown", "expected"),
    [
        (19, 0, PASSED),  # 19/20 = %95
        (18, 0, FAILED),
        (18, 1, INCONCLUSIVE),  # unknown basariliysa %95, degilse %90
        (19, 1, PASSED),  # unknown basarisiz sayilsa bile %95
        (17, 1, FAILED),  # unknown basarili sayilsa bile %90
        (18, 2, INCONCLUSIVE),  # bilinenlerin hepsi basarili ama payda unknown'lari da icerir
    ],
)
def test_unknown_is_counted_both_ways(numerator: int, unknown: int, expected: str) -> None:
    rate = Rate()
    for index in range(20):
        if index < unknown:
            rate.add(PLANNED[0], success=None)
        else:
            rate.add(PLANNED[0], success=index - unknown < numerator)
    assert rate.verdict(0.95) == expected


def test_too_little_support_is_inconclusive() -> None:
    """Tek niyet eslesmesi 1/1 ile %100 kabul olamaz."""
    rate = Rate()
    rate.add(PLANNED[0], success=True)
    assert rate.verdict(0.8, min_support=30) == INCONCLUSIVE
    assert rate.verdict(0.8, min_support=1) == PASSED


def test_too_few_distinct_days_is_inconclusive() -> None:
    rate = Rate()
    for _ in range(40):
        rate.add(PLANNED[0], success=True)
    assert rate.verdict(0.8, min_support=30, min_days=10) == INCONCLUSIVE


def test_an_empty_rate_is_inconclusive() -> None:
    assert Rate().verdict(0.5, min_support=0) == INCONCLUSIVE


# --------------------------------------------------------------------------
# Paydalar
# --------------------------------------------------------------------------


def test_a_clean_run_passes_every_metric() -> None:
    summary = summarize(PLANNED, SYMBOLS, complete_days(), every(), THRESHOLDS)
    total = summary["total"]
    assert summary["days"] == {
        DAY_COMPLETE: 4,
        DAY_INCOMPLETE: 0,
        DAY_NOT_STARTED: 0,
        DAY_UNKNOWN: 0,
    }
    assert total["iex_window_initial"]["denominator"] == 8
    assert total["iex_window_initial"]["verdict"] == PASSED
    assert total["range_within_bps"]["verdict"] == PASSED
    assert total["intent_agreement"]["verdict"] == PASSED


def test_missing_days_stay_in_the_denominator() -> None:
    """Baslamamis gunun sembol-gunleri unknown olarak paydada kalir."""
    days = [*complete_days()[:3], Day(PLANNED[3], DAY_NOT_STARTED, "gec baslangic")]
    results = [r for r in every() if r.day != PLANNED[3]]
    summary = summarize(PLANNED, SYMBOLS, days, results, THRESHOLDS)
    completeness = summary["total"]["iex_window_initial"]
    assert (completeness["numerator"], completeness["denominator"], completeness["unknown"]) == (
        6,
        8,
        2,
    )
    assert completeness["verdict"] == INCONCLUSIVE
    assert summary["days"][DAY_NOT_STARTED] == 1
    assert summary["day_list"][3] == {
        "day": PLANNED[3].isoformat(),
        "status": DAY_NOT_STARTED,
        "reason": "gec baslangic",
    }


def test_a_day_without_evidence_is_unknown_not_not_started() -> None:
    """Ozet yoklugu `baslamadi` kaniti degildir (Codex 6155755867)."""
    results = [r for r in every() if r.day in PLANNED[:2]]
    summary = summarize(PLANNED, SYMBOLS, complete_days()[:2], results, THRESHOLDS)
    assert summary["days"][DAY_UNKNOWN] == 2
    assert summary["days"][DAY_NOT_STARTED] == 0
    assert {entry["reason"] for entry in summary["day_list"][2:]} == {"kanit yok"}
    completeness = summary["total"]["iex_window_initial"]
    assert (completeness["denominator"], completeness["unknown"]) == (8, 4)


def test_an_incomplete_window_counts_against_completeness() -> None:
    gap = replace(GOOD, iex_present=14, or_high_bps=None, or_low_bps=None, signal=SIGNAL_MISMATCH)
    results = [*every()[:-1], result(PLANNED[3], "QQQ", gap)]
    completeness = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)["total"][
        "iex_window_initial"
    ]
    assert (completeness["numerator"], completeness["denominator"]) == (7, 8)
    assert completeness["verdict"] == FAILED


def test_a_window_completed_later_is_counted_separately() -> None:
    late = replace(GOOD, iex_present=14, iex_completed_later=True)
    results = [*every()[:-1], result(PLANNED[3], "QQQ", late)]
    summary = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)
    completeness = summary["total"]["iex_window_initial"]
    assert completeness["numerator"] == 7
    assert summary["total"]["iex_window_delayed"] == {
        "completed_later": 1,
        "incomplete_at_t_star": 1,
    }
    assert summary["total"]["range_within_bps"]["denominator"] == 8


def test_missing_sip_makes_range_and_intent_unknown() -> None:
    results = [*every()[:-1], result(PLANNED[3], "QQQ", sip=False)]
    total = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)["total"]
    assert total["range_within_bps"]["unknown"] == 1
    assert total["intent_agreement"]["unknown"] == 1
    assert total["iex_window_initial"]["unknown"] == 0


@pytest.mark.parametrize(
    ("high", "low", "passes"),
    [
        (5.0, -5.0, True),
        (-5.0, 5.0, True),
        (5.01, 0.0, False),
        (0.0, -5.01, False),
        (100.0, 0.0, False),
        (-100.0, 0.0, False),
        (0.0, -100.0, False),
    ],
)
def test_the_range_threshold_is_absolute(high: float, low: float, passes: bool) -> None:
    """Isaretli fark raporda kalir; kabul |bps| ile (Codex 6155755867)."""
    edge = replace(GOOD, or_high_bps=high, or_low_bps=low)
    results = [*every()[:-1], result(PLANNED[3], "QQQ", edge)]
    rate = summarize(PLANNED, SYMBOLS, complete_days(), results, Thresholds())["total"][
        "range_within_bps"
    ]
    assert rate["numerator"] == (8 if passes else 7)


def test_an_invalid_denominator_is_unknown() -> None:
    invalid = replace(GOOD, or_high_bps=None, or_low_bps=None, range_status=RANGE_INVALID)
    results = [*every()[:-1], result(PLANNED[3], "QQQ", invalid)]
    rate = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)["total"][
        "range_within_bps"
    ]
    assert (rate["numerator"], rate["denominator"], rate["unknown"]) == (7, 8, 1)


def test_an_incomplete_sip_window_is_outside_the_range_measure() -> None:
    """Olcu "iki pencere tamsa" tanimli: eksik SIP penceresi ayri sayilir."""
    gap = replace(GOOD, or_high_bps=None, or_low_bps=None, range_status=RANGE_SIP_INCOMPLETE)
    results = [*every()[:-1], result(PLANNED[3], "QQQ", gap)]
    rate = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)["total"][
        "range_within_bps"
    ]
    assert (rate["numerator"], rate["denominator"], rate["unknown"]) == (7, 7, 0)
    assert rate["sip_window_incomplete"] == 1


def test_unobserved_symbol_days_are_unknown_in_the_range_denominator() -> None:
    """Codex 6158917217 ornegi: 20 gun x 11 sembol; ilk 10 gunun 110 sonucu
    iyi, kalan 110 sembol-gunun sonucu yok. Aralik 110/220, unknown 110."""
    days = [date(2026, 11, 2) + timedelta(days=offset) for offset in range(20)]
    symbols = tuple(f"S{index}" for index in range(11))
    results = [
        SymbolDay(day, symbol, replace(GOOD, symbol=symbol), sip_available=True)
        for day in days[:10]
        for symbol in symbols
    ]
    statuses = [Day(day, DAY_COMPLETE) for day in days[:10]]
    rate = summarize(days, symbols, statuses, results, Thresholds())["total"]["range_within_bps"]
    assert (rate["numerator"], rate["denominator"], rate["unknown"]) == (110, 220, 110)
    assert rate["verdict"] == INCONCLUSIVE


def unmeasured(status: str) -> Comparison:
    return replace(GOOD, or_high_bps=None, or_low_bps=None, range_status=status)


@pytest.mark.parametrize(
    ("comparison", "expected"),
    [
        (None, (7, 8, 1, 0)),
        (unmeasured(RANGE_UNKNOWN), (7, 8, 1, 0)),
        (unmeasured(RANGE_SIP_MISSING), (7, 8, 1, 0)),
        (unmeasured(RANGE_IEX_INCOMPLETE), (7, 7, 0, 1)),
    ],
)
def test_only_an_observed_incomplete_window_leaves_the_range_denominator(
    comparison: Comparison | None, expected: tuple[int, int, int, int]
) -> None:
    """Kosulun saglanip saglanmadigi bilinmeyen sembol-gun `unknown`; yalnizca
    eksikligi gozlenen IEX penceresi kosul disi ve ayri sayilir."""
    results = [*every()[:-1], result(PLANNED[3], "QQQ", comparison)]
    rate = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)["total"][
        "range_within_bps"
    ]
    assert (
        rate["numerator"],
        rate["denominator"],
        rate["unknown"],
        rate["iex_window_incomplete"],
    ) == expected


@pytest.mark.parametrize(("high", "low"), [(6.0, 0.0), (0.0, -6.0)])
def test_a_range_beyond_the_threshold_fails_that_symbol_day(high: float, low: float) -> None:
    wide = replace(GOOD, or_high_bps=high, or_low_bps=low)
    results = [*every()[:-1], result(PLANNED[3], "QQQ", wide)]
    summary = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)
    assert summary["total"]["range_within_bps"]["numerator"] == 7
    assert summary["per_symbol"]["QQQ"]["range_within_bps"]["numerator"] == 3


def test_an_unknown_first_intent_is_unknown_not_agreement() -> None:
    gap = replace(GOOD, signal=SIGNAL_UNKNOWN, iex_first_minute=None)
    results = [*every()[:-1], result(PLANNED[3], "QQQ", gap)]
    intent = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)["total"][
        "intent_agreement"
    ]
    assert (intent["numerator"], intent["denominator"], intent["unknown"]) == (7, 8, 1)
    assert intent["no_intent"] == 0


def test_no_intent_on_both_sides_is_its_own_counter() -> None:
    quiet = replace(GOOD, signal=SIGNAL_NONE, iex_first_minute=None, sip_first_minute=None)
    summary = summarize(PLANNED, SYMBOLS, complete_days(), every(quiet), THRESHOLDS)
    intent = summary["total"]["intent_agreement"]
    assert intent["no_intent"] == 8
    assert intent["denominator"] == 0
    assert intent["verdict"] == INCONCLUSIVE


def test_one_failing_symbol_is_visible_per_symbol() -> None:
    gap = replace(GOOD, iex_present=0, signal=SIGNAL_MISMATCH)
    results = [result(day, "SPY") for day in PLANNED] + [result(day, "QQQ", gap) for day in PLANNED]
    summary = summarize(PLANNED, SYMBOLS, complete_days(), results, THRESHOLDS)
    assert summary["per_symbol"]["QQQ"]["iex_window_initial"]["numerator"] == 0
    assert summary["per_symbol"]["SPY"]["iex_window_initial"]["numerator"] == 4
    assert "verdict" not in summary["per_symbol"]["QQQ"]["iex_window_initial"]


# --------------------------------------------------------------------------
# Girdi ve cikti sinirlari
# --------------------------------------------------------------------------


def test_unplanned_or_duplicate_input_is_refused() -> None:
    extra = result(PLANNED[0] - timedelta(days=1), "SPY")
    with pytest.raises(ValueError, match="plan disi"):
        summarize(PLANNED, SYMBOLS, complete_days(), [*every(), extra], THRESHOLDS)
    with pytest.raises(ValueError, match="iki kez"):
        summarize(PLANNED, SYMBOLS, complete_days(), [*every(), every()[0]], THRESHOLDS)
    with pytest.raises(ValueError, match="plan disi gun"):
        summarize(PLANNED, SYMBOLS, [Day(date(2026, 1, 1), DAY_COMPLETE)], [], THRESHOLDS)
    with pytest.raises(ValueError, match="tekrar"):
        summarize([PLANNED[0], PLANNED[0]], SYMBOLS, [], [], THRESHOLDS)


def test_a_day_status_needs_a_reason_unless_complete() -> None:
    with pytest.raises(ValueError, match="sebebi"):
        Day(PLANNED[0], DAY_INCOMPLETE)
    with pytest.raises(ValueError, match="sebebi"):
        Day(PLANNED[0], DAY_COMPLETE, "gereksiz")
    with pytest.raises(ValueError, match="bilinmeyen"):
        Day(PLANNED[0], "yarim")


def test_the_summary_is_json_and_marks_thresholds_as_proposals() -> None:
    summary = summarize(PLANNED, SYMBOLS, complete_days(), every(), Thresholds())
    text = json.dumps(summary)
    assert json.loads(text) == summary
    assert summary["thresholds_are_proposals"] is True


def test_the_summary_carries_no_price_fields() -> None:
    summary = summarize(PLANNED, SYMBOLS, complete_days(), every(), THRESHOLDS)
    keys: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            keys.update(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(summary)
    assert not keys & {"open", "high", "low", "close", "price", "or_high", "or_low", "equity"}
