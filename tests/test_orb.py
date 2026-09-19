"""Acilis araligi kirilimi stratejisi testleri.

Her test tek bir karar kuralini dogruluyor. Stratejinin cogu cagrisi
None dondurur - islem yapmamak normal ve dogru sonuctur; bu yuzden
"ne zaman islem YAPMADIGI" en az "ne zaman yaptigi" kadar test
ediliyor.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import SESSION_OPEN, make_bars, make_context, make_session
from tlab.core.types import Bar, Position, Side
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

# Acilis araligi: 99,50 - 100,50 (15 bar, spread 0,5)
OR_HIGH = 100.5
OR_LOW = 99.5


def scenario_bars(
    *,
    breakout_close: float | None = None,
    breakout_volume: float = 30_000,
    count: int = 30,
) -> list[Bar]:
    """Aralik olusmus bir seans uretir; istege bagli kirilim bariyla.

    Ilk 15 bar acilis araligini olusturur, kalanlar aralik icinde
    seyreder. `breakout_close` verilirse son bar o fiyata kapanir ve
    hacmi yukselir.
    """
    bars = make_bars(count, base=100.0, spread=0.5, volume=10_000)
    if breakout_close is None:
        return bars

    last = bars[-1]
    bars[-1] = last.model_copy(
        update={
            "open": 100.0,
            "close": breakout_close,
            "high": max(breakout_close, last.high),
            "low": min(breakout_close, last.low),
            "volume": breakout_volume,
        }
    )
    return bars


@pytest.fixture
def strategy() -> OpeningRangeBreakout:
    return OpeningRangeBreakout(ORBParams())


# --------------------------------------------------------------------------
# Kirilim var
# --------------------------------------------------------------------------


def test_upward_breakout_produces_a_long_intent(strategy: OpeningRangeBreakout) -> None:
    ctx = make_context(bars=scenario_bars(breakout_close=100.8))
    intent = strategy.decide(ctx)

    assert intent is not None
    assert intent.side is Side.BUY
    assert intent.reference_price == pytest.approx(100.8)
    # Stop, araligin karsi ucunda: kirilim gecersizse oraya donulur.
    assert intent.stop_loss == pytest.approx(OR_LOW)
    # Hedef, riskin 1,5 kati.
    assert intent.reward_risk == pytest.approx(1.5)
    assert intent.strategy_id == "orb"


def test_downward_breakout_produces_a_short_intent(strategy: OpeningRangeBreakout) -> None:
    ctx = make_context(bars=scenario_bars(breakout_close=99.2))
    intent = strategy.decide(ctx)

    assert intent is not None
    assert intent.side is Side.SELL
    assert intent.stop_loss == pytest.approx(OR_HIGH)
    assert intent.take_profit < intent.reference_price


def test_short_can_be_disabled() -> None:
    strategy = OpeningRangeBreakout(ORBParams(allow_short=False))
    assert strategy.decide(make_context(bars=scenario_bars(breakout_close=99.2))) is None


def test_features_snapshot_carries_the_learning_fuel(strategy: OpeningRangeBreakout) -> None:
    """Kaydedilmeyen bir olcu ileride geri donup toplanamaz."""
    intent = strategy.decide(make_context(bars=scenario_bars(breakout_close=100.8)))
    assert intent is not None
    for key in (
        "price",
        "or_high",
        "or_low",
        "or_range",
        "atr",
        "rvol",
        "risk_per_share",
        "minutes_since_open",
        "spread_bps",
        "vwap",
        "dist_to_vwap_bps",
    ):
        assert key in intent.features, f"eksik ozellik: {key}"


# --------------------------------------------------------------------------
# Kirilim yok / kosullar saglanmiyor
# --------------------------------------------------------------------------


def test_price_inside_the_range_is_not_a_breakout(strategy: OpeningRangeBreakout) -> None:
    assert strategy.decide(make_context(bars=scenario_bars())) is None


def test_breakout_without_volume_is_ignored(strategy: OpeningRangeBreakout) -> None:
    """Hacimsiz kirilimlar cogunlukla geri alinir."""
    ctx = make_context(bars=scenario_bars(breakout_close=100.8, breakout_volume=9_000))
    assert strategy.decide(ctx) is None


def test_overextended_breakout_is_skipped(strategy: OpeningRangeBreakout) -> None:
    """Kacan trenin arkasindan kosmak stop'u uzatir, girisi kotulestirir."""
    ctx = make_context(bars=scenario_bars(breakout_close=115.0))
    assert strategy.decide(ctx) is None


def test_incomplete_opening_range_blocks_entry(strategy: OpeningRangeBreakout) -> None:
    """Aralik olusmadan kirilimdan soz edilemez."""
    bars = make_bars(10, base=100.0, spread=0.5)
    session = make_session(SESSION_OPEN + timedelta(minutes=10))
    assert strategy.decide(make_context(bars=bars, session=session)) is None


def test_existing_position_blocks_a_second_entry(strategy: OpeningRangeBreakout) -> None:
    """Ayni fikre iki kez risk alinmaz."""
    position = Position(
        symbol="SPY", side=Side.BUY, qty=10, avg_entry_price=100.0, current_price=100.8
    )
    ctx = make_context(bars=scenario_bars(breakout_close=100.8), positions={"SPY": position})
    assert strategy.decide(ctx) is None


@pytest.mark.parametrize("minutes", [5, 385, 400])
def test_entry_only_during_regular_session(strategy: OpeningRangeBreakout, minutes: int) -> None:
    """Acilis araligi olusurken, kapanis tamponunda ve seans disinda giris yok."""
    session = make_session(SESSION_OPEN + timedelta(minutes=minutes))
    ctx = make_context(bars=scenario_bars(breakout_close=100.8), session=session)
    assert strategy.decide(ctx) is None


def test_entry_window_closes_after_configured_minutes() -> None:
    """Gun ilerledikce kirilimlarin kalicilik ihtimali duser."""
    strategy = OpeningRangeBreakout(ORBParams(entry_window_minutes=60))
    session = make_session(SESSION_OPEN + timedelta(minutes=90))
    bars = scenario_bars(breakout_close=100.8, count=90)
    assert strategy.decide(make_context(bars=bars, session=session)) is None


def test_not_enough_history_blocks_entry(strategy: OpeningRangeBreakout) -> None:
    """ATR ve RVOL hesaplanamiyorsa karar verilmez."""
    ctx = make_context(bars=scenario_bars(breakout_close=100.8, count=18))
    assert strategy.decide(ctx) is None


def test_empty_bars_are_handled(strategy: OpeningRangeBreakout) -> None:
    assert strategy.decide(make_context(bars=[])) is None


# --------------------------------------------------------------------------
# Stop mesafesi
# --------------------------------------------------------------------------


def test_stop_keeps_a_minimum_distance_in_a_tight_range() -> None:
    """Dar aralikta yapisal stop fiyata cok yakin duser.

    Boyle bir stop piyasa gurultusuyle tetiklenir ve yuvarlandiktan
    sonra girisle cakisabilir; asgari mesafe bunu engeller.
    """
    # Cok dar aralik: 99,99 - 100,01. Yapisal stop girise 0,03 uzakta.
    bars = make_bars(30, base=100.0, spread=0.01, volume=10_000)
    bars[-1] = bars[-1].model_copy(
        update={"open": 100.0, "close": 100.02, "high": 100.02, "low": 99.99, "volume": 30_000.0}
    )
    structural_stop = 99.99

    loose = OpeningRangeBreakout(ORBParams(min_stop_bps=0.1, min_stop_atr_frac=0.0))
    tight = OpeningRangeBreakout(ORBParams(min_stop_bps=50.0, min_stop_atr_frac=0.0))

    without_floor = loose.decide(make_context(bars=bars))
    with_floor = tight.decide(make_context(bars=bars))
    assert without_floor is not None and with_floor is not None

    # Taban yokken yapisal stop kullanilir.
    assert without_floor.stop_loss == pytest.approx(structural_stop)
    # Taban devredeyken stop asgari mesafeye itilir (50 bps = %0,5).
    assert with_floor.stop_loss < structural_stop
    assert with_floor.stop_loss == pytest.approx(100.02 * (1 - 0.005))
    assert with_floor.risk_per_share > without_floor.risk_per_share


# --------------------------------------------------------------------------
# Parametre kimligi
# --------------------------------------------------------------------------


def test_params_version_is_stable_for_identical_params() -> None:
    assert OpeningRangeBreakout(ORBParams()).params_version == (
        OpeningRangeBreakout(ORBParams()).params_version
    )


def test_params_version_changes_when_params_change() -> None:
    """Ayni kimlikle farkli ayar, journal'i yalan soyler hale getirirdi."""
    base = OpeningRangeBreakout(ORBParams()).params_version
    tweaked = OpeningRangeBreakout(ORBParams(target_r=2.0)).params_version
    assert base != tweaked
    assert tweaked.startswith("orb-")


def test_confidence_rises_with_volume(strategy: OpeningRangeBreakout) -> None:
    quiet = strategy.decide(
        make_context(bars=scenario_bars(breakout_close=100.8, breakout_volume=13_000))
    )
    loud = strategy.decide(
        make_context(bars=scenario_bars(breakout_close=100.8, breakout_volume=60_000))
    )
    assert quiet is not None and loud is not None
    assert loud.confidence > quiet.confidence
    assert 0.0 <= quiet.confidence <= 1.0
