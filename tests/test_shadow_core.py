"""Golge gozlem cekirdegi: ayni karar yolu, ayni izgara, fiyatsiz karsilastirma.

Tasarim: docs/designs/shadow-observation.md (Codex 6152090021). Ag yok,
anahtar yok, emir yok. Testler sentetik barlarla sunlari gosterir:

  * iki taraf ayni gorunum kuralindan gecer (gecmis baslangici, kapanmis bar);
  * seans dongununkiyle ayni kurulur (yarim gun dahil);
  * niyet riskten oncedir ve sentetik durumla uretilir;
  * karsilastirma fiyat tasimaz, olcum anlari tanimlidir.
"""

from __future__ import annotations

import ast
import dataclasses
import socket
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import SESSION_OPEN, make_bars, make_session
from tlab.config import Config, load_config
from tlab.core.types import Bar, Intent, Side, Timeframe
from tlab.features.context import Context, SessionPhase, SessionState, apply_market_close
from tlab.shadow.core import (
    RANGE_COMPUTED,
    RANGE_IEX_INCOMPLETE,
    RANGE_SIP_INCOMPLETE,
    RANGE_SIP_MISSING,
    SIGNAL_MATCH,
    SIGNAL_MISMATCH,
    SIGNAL_NONE,
    SIGNAL_UNKNOWN,
    SYNTHETIC_ACCOUNT,
    Comparison,
    Turn,
    _bps,
    compare_symbol_day,
    intent_at,
    session_at,
    visible_bars,
)
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

REPO = Path(__file__).resolve().parents[1]
REGULAR_CLOSE = SESSION_OPEN + timedelta(hours=6, minutes=30)
PARAMS = ORBParams()
STRATEGY = OpeningRangeBreakout(PARAMS)


@pytest.fixture
def config(project_root: Path) -> Config:
    return load_config(project_root)


@pytest.fixture
def session_for(config: Config) -> Callable[[datetime], SessionState]:
    def build(moment: datetime) -> SessionState:
        return session_at(
            moment,
            config=config,
            opening_range_minutes=PARAMS.opening_range_minutes,
            market_close=REGULAR_CLOSE,
        )

    return build


def breakout_day(*, at: int = 29, close: float = 100.8, base: float = 100.0) -> list[Bar]:
    """Acilis araligi 99,50-100,50; `at` dakikasindaki bar kirilimla kapanir."""
    bars = make_bars(at + 31, base=base, spread=0.5, volume=10_000)
    bars[at] = bars[at].model_copy(
        update={
            "open": base,
            "close": close,
            "high": max(close, base + 0.5),
            "low": min(close, base - 0.5),
            "volume": 30_000.0,
        }
    )
    return bars


def without_minute(bars: list[Bar], minute: int) -> list[Bar]:
    return [bar for bar in bars if bar.ts != SESSION_OPEN + timedelta(minutes=minute)]


FULL = range(1, 122)
"""Turlar giris penceresinin sonuna kadar: planli dakikalar 15 ... 120."""


def grid(minutes: range, *, seconds: int = 5) -> list[datetime]:
    """Canli dongunun turlari: dakikanin birkac saniye sonrasi."""
    return [SESSION_OPEN + timedelta(minutes=m, seconds=seconds) for m in minutes]


def turns(bars: list[Bar], moments: list[datetime]) -> list[Turn]:
    return [
        Turn(moment, visible_bars(bars, moment, timeframe=Timeframe.M1, history_days=3))
        for moment in moments
    ]


def compare(
    iex: list[Turn],
    sip: list[Turn],
    session_for: Callable[[datetime], SessionState],
) -> Comparison:
    return compare_symbol_day(
        "SPY",
        iex,
        sip,
        session_for=session_for,
        strategy=STRATEGY,
        opening_range_minutes=PARAMS.opening_range_minutes,
        entry_window_minutes=PARAMS.entry_window_minutes,
        timeframe=Timeframe.M1,
    )


# --------------------------------------------------------------------------
# Gorunum: gecmis baslangici ve kapanmis bar
# --------------------------------------------------------------------------


def test_the_view_holds_only_closed_bars() -> None:
    bars = make_bars(5)
    moment = SESSION_OPEN + timedelta(minutes=3)
    seen = visible_bars(bars, moment, timeframe=Timeframe.M1, history_days=3)
    assert [bar.ts for bar in seen] == [SESSION_OPEN + timedelta(minutes=m) for m in range(3)]


def test_the_view_starts_history_days_before_the_turn() -> None:
    """Dongu gecmisi her turda `an - history_days`ten ister; SIP de oyle."""
    moment = SESSION_OPEN + timedelta(minutes=1)
    old = make_bars(2, start=moment - timedelta(days=3, minutes=1))
    seen = visible_bars(old, moment, timeframe=Timeframe.M1, history_days=3)
    assert [bar.ts for bar in seen] == [moment - timedelta(days=3)]


def test_the_view_is_time_ordered_whatever_the_input_order() -> None:
    bars = list(reversed(make_bars(4)))
    moment = SESSION_OPEN + timedelta(minutes=10)
    seen = visible_bars(bars, moment, timeframe=Timeframe.M1, history_days=3)
    assert [bar.ts for bar in seen] == sorted(bar.ts for bar in bars)


def test_the_view_respects_the_bar_duration() -> None:
    bars = make_bars(3)
    moment = SESSION_OPEN + timedelta(minutes=4)
    seen = visible_bars(bars, moment, timeframe=Timeframe.M5, history_days=3)
    assert seen == ()


# --------------------------------------------------------------------------
# Seans: dongununkiyle ayni
# --------------------------------------------------------------------------


def test_the_session_matches_the_loop_on_a_regular_day(
    session_for: Callable[[datetime], SessionState],
) -> None:
    moment = SESSION_OPEN + timedelta(minutes=30)
    assert session_for(moment) == make_session(moment)


def test_an_early_close_shortens_the_session(config: Config) -> None:
    early = SESSION_OPEN + timedelta(hours=3, minutes=30)
    moment = early - timedelta(minutes=5)
    state = session_at(moment, config=config, opening_range_minutes=15, market_close=early)
    assert state.session_close == early
    assert state.flatten_at == early - timedelta(minutes=10)
    assert state.phase is SessionPhase.FLATTEN
    assert not state.can_open_new_positions


def test_a_later_calendar_close_never_extends_the_session(config: Config) -> None:
    late = REGULAR_CLOSE + timedelta(hours=1)
    moment = SESSION_OPEN + timedelta(minutes=30)
    state = session_at(moment, config=config, opening_range_minutes=15, market_close=late)
    assert state.session_close == REGULAR_CLOSE


def test_the_market_close_helper_is_the_one_the_loop_uses() -> None:
    """Dongu ayni yardimciyi cagirir; kaynakta ayri bir kopya yok."""
    runner = (REPO / "src/tlab/engine/runner.py").read_text(encoding="utf-8")
    assert "apply_market_close(" in runner
    assert "min(session.session_close" not in runner
    state = apply_market_close(make_session(), REGULAR_CLOSE, flatten_before_close_minutes=10)
    assert state == make_session()


# --------------------------------------------------------------------------
# Niyet: riskten once, sentetik durum
# --------------------------------------------------------------------------


def test_the_intent_comes_from_the_strategy_on_closed_bars(
    session_for: Callable[[datetime], SessionState],
) -> None:
    bars = breakout_day(at=29)
    before = SESSION_OPEN + timedelta(minutes=29, seconds=59)
    after = SESSION_OPEN + timedelta(minutes=30)
    seen_before = visible_bars(bars, before, timeframe=Timeframe.M1, history_days=3)
    seen_after = visible_bars(bars, after, timeframe=Timeframe.M1, history_days=3)
    m1 = Timeframe.M1
    assert (
        intent_at("SPY", seen_before, session_for(before), strategy=STRATEGY, timeframe=m1) is None
    )
    intent = intent_at("SPY", seen_after, session_for(after), strategy=STRATEGY, timeframe=m1)
    assert intent is not None
    assert intent.side is Side.BUY


def test_no_intent_outside_the_regular_phase(
    session_for: Callable[[datetime], SessionState],
) -> None:
    bars = make_bars(10)
    moment = SESSION_OPEN + timedelta(minutes=10)
    seen = visible_bars(bars, moment, timeframe=Timeframe.M1, history_days=3)
    assert session_for(moment).phase is SessionPhase.OPENING_RANGE
    assert (
        intent_at("SPY", seen, session_for(moment), strategy=STRATEGY, timeframe=Timeframe.M1)
        is None
    )


class AlwaysLong:
    """Her baglamda niyet ureten strateji: fazi stratejiye birakmayan bir yol yakalanir."""

    strategy_id = "always-long"
    params_version = "v0"

    def decide(self, ctx: Context) -> Intent | None:
        return Intent(
            strategy_id=self.strategy_id,
            symbol=ctx.symbol,
            side=Side.BUY,
            reference_price=100.0,
            stop_loss=99.0,
            take_profit=102.0,
        )


@pytest.mark.parametrize("minute", [-5, 10, 385])
def test_only_the_regular_phase_is_evaluated_whatever_the_strategy(
    minute: int, session_for: Callable[[datetime], SessionState]
) -> None:
    """Dongu yeni girisi yalnizca normal seansta degerlendirir; saf yol da oyle."""
    moment = SESSION_OPEN + timedelta(minutes=minute)
    bars = visible_bars(make_bars(400), moment, timeframe=Timeframe.M1, history_days=3) or tuple(
        make_bars(1, start=SESSION_OPEN - timedelta(days=1))
    )
    session = session_for(moment)
    assert not session.can_open_new_positions
    assert intent_at("SPY", bars, session, strategy=AlwaysLong(), timeframe=Timeframe.M1) is None
    regular = SESSION_OPEN + timedelta(minutes=30)
    seen = visible_bars(make_bars(40), regular, timeframe=Timeframe.M1, history_days=3)
    assert (
        intent_at("SPY", seen, session_for(regular), strategy=AlwaysLong(), timeframe=Timeframe.M1)
        is not None
    )


def test_no_intent_without_closed_bars(session_for: Callable[[datetime], SessionState]) -> None:
    moment = SESSION_OPEN + timedelta(minutes=30)
    assert (
        intent_at("SPY", (), session_for(moment), strategy=STRATEGY, timeframe=Timeframe.M1) is None
    )


def test_the_synthetic_state_is_fixed() -> None:
    assert SYNTHETIC_ACCOUNT.equity == 100_000.0
    assert not SYNTHETIC_ACCOUNT.trading_blocked


# --------------------------------------------------------------------------
# Karsilastirma
# --------------------------------------------------------------------------


def test_identical_feeds_match(session_for: Callable[[datetime], SessionState]) -> None:
    bars = breakout_day(at=29)
    moments = grid(FULL)
    result = compare(turns(bars, moments), turns(bars, moments), session_for)
    assert (result.iex_present, result.sip_present, result.window_expected) == (15, 15, 15)
    assert (result.or_high_bps, result.or_low_bps) == (0.0, 0.0)
    assert result.signal == SIGNAL_MATCH
    assert (
        result.iex_first_minute == result.sip_first_minute == pytest.approx(30 + 5 / 60, abs=1e-3)
    )
    assert not result.iex_completed_later
    assert result.iex_unknown_turns == 0


def test_the_range_difference_is_in_basis_points(
    session_for: Callable[[datetime], SessionState],
) -> None:
    sip = breakout_day(at=29)
    iex = [bar.model_copy(update={"high": bar.high * 1.0005}) for bar in sip]
    moments = grid(FULL)
    result = compare(turns(iex, moments), turns(sip, moments), session_for)
    assert result.or_high_bps == pytest.approx(5.0, abs=1e-3)
    assert result.or_low_bps == 0.0


def test_a_missing_iex_minute_is_counted_at_t_star(
    session_for: Callable[[datetime], SessionState],
) -> None:
    """Pencere tamligi, pencerenin veride ilk kapandigi turda olculur."""
    sip = breakout_day(at=29)
    iex = without_minute(sip, 7)
    moments = grid(FULL)
    result = compare(turns(iex, moments), turns(sip, moments), session_for)
    assert (result.iex_present, result.sip_present) == (14, 15)
    assert (result.or_high_bps, result.or_low_bps) == (None, None)
    assert not result.iex_completed_later
    assert result.signal == SIGNAL_MISMATCH
    assert result.iex_first_minute is None


def test_a_late_iex_bar_is_counted_as_completed_later(
    session_for: Callable[[datetime], SessionState],
) -> None:
    """Gec gelen bar ilk sonucu degistirmez; ayrica sayilir."""
    sip = breakout_day(at=29)
    moments = grid(FULL)
    late = SESSION_OPEN + timedelta(minutes=20)
    iex_turns = [
        Turn(
            moment,
            visible_bars(
                sip if moment >= late else without_minute(sip, 7),
                moment,
                timeframe=Timeframe.M1,
                history_days=3,
            ),
        )
        for moment in moments
    ]
    result = compare(iex_turns, turns(sip, moments), session_for)
    assert result.iex_present == 14
    assert result.iex_completed_later
    assert (result.or_high_bps, result.or_low_bps) == (0.0, 0.0)
    assert result.signal == SIGNAL_MATCH


def test_without_a_turn_after_t_star_the_window_is_unknown(
    session_for: Callable[[datetime], SessionState],
) -> None:
    bars = breakout_day(at=29)[:15]
    moments = grid(range(1, 16))
    result = compare(turns(bars, moments), turns(bars, moments), session_for)
    assert result.iex_present is None
    assert result.sip_present is None


@pytest.mark.parametrize(("missing", "present"), [(None, 15), (7, 14), (14, 14)])
def test_the_window_is_measured_at_t_star_even_if_no_later_bar_arrives(
    missing: int | None, present: int, session_for: Callable[[datetime], SessionState]
) -> None:
    """t* saatle secilir: sonraki bar hic gelmese de sayim yapilir ve
    eksiklik gorunmez kalmaz."""
    bars = make_bars(15, spread=0.5)
    if missing is not None:
        bars = without_minute(bars, missing)
    moments = grid(FULL)
    result = compare(turns(bars, moments), turns(bars, moments), session_for)
    assert (result.iex_present, result.sip_present) == (present, present)


def test_t_star_is_unknown_when_its_turn_failed(
    session_for: Callable[[datetime], SessionState],
) -> None:
    bars = breakout_day(at=29)
    moments = grid(FULL)
    star = SESSION_OPEN + timedelta(minutes=16, seconds=5)
    iex_turns = [Turn(t.moment, None) if t.moment == star else t for t in turns(bars, moments)]
    result = compare(iex_turns, turns(bars, moments), session_for)
    assert result.iex_present is None
    assert not result.iex_completed_later
    assert (result.or_high_bps, result.or_low_bps) == (0.0, 0.0)


def test_t_star_needs_a_turn_within_the_slack(
    session_for: Callable[[datetime], SessionState],
) -> None:
    """Pencere sonu + D'den sonraki 2 dk icinde tur yoksa tamlik bilinmez."""
    bars = breakout_day(at=29)
    moments = [m for m in grid(FULL) if not 16 <= (m - SESSION_OPEN).seconds // 60 <= 18]
    result = compare(turns(bars, moments), turns(bars, moments), session_for)
    assert result.iex_present is None


def test_unknown_turns_before_the_first_intent_make_it_unknown(
    session_for: Callable[[datetime], SessionState],
) -> None:
    bars = breakout_day(at=29)
    moments = grid(FULL)
    iex_turns = [
        Turn(t.moment, None) if t.moment < SESSION_OPEN + timedelta(minutes=17) else t
        for t in turns(bars, moments)
    ]
    result = compare(iex_turns, turns(bars, moments), session_for)
    assert result.iex_unknown_turns == 16
    assert result.iex_present is None
    assert result.signal == SIGNAL_UNKNOWN
    assert result.iex_first_minute is None


def test_a_missing_turn_before_the_first_intent_makes_it_unknown(
    session_for: Callable[[datetime], SessionState],
) -> None:
    bars = breakout_day(at=40)
    moments = [m for m in grid(FULL) if (m - SESSION_OPEN).seconds // 60 != 30]
    result = compare(turns(bars, moments), turns(bars, moments), session_for)
    assert result.signal == SIGNAL_UNKNOWN


def test_gaps_after_the_first_intent_do_not_matter(
    session_for: Callable[[datetime], SessionState],
) -> None:
    bars = breakout_day(at=29)
    moments = grid(FULL)
    gap = range(40, 51)
    iex_turns = [
        Turn(t.moment, None) if (t.moment - SESSION_OPEN).seconds // 60 in gap else t
        for t in turns(bars, moments)
    ]
    result = compare(iex_turns, turns(bars, moments), session_for)
    assert result.iex_unknown_turns == 11
    assert result.iex_present == 15
    assert result.signal == SIGNAL_MATCH


def test_no_intent_on_either_side_is_not_agreement(
    session_for: Callable[[datetime], SessionState],
) -> None:
    quiet = make_bars(122, spread=0.5)
    moments = grid(FULL)
    result = compare(turns(quiet, moments), turns(quiet, moments), session_for)
    assert result.signal == SIGNAL_NONE
    assert result.signal != SIGNAL_MATCH


@pytest.mark.parametrize(("iex_at", "expected"), [(30, SIGNAL_MATCH), (31, SIGNAL_MISMATCH)])
def test_signal_timing_tolerance_is_one_minute(
    iex_at: int, expected: str, session_for: Callable[[datetime], SessionState]
) -> None:
    sip = breakout_day(at=29)
    iex = breakout_day(at=iex_at)
    moments = grid(FULL)
    result = compare(turns(iex, moments), turns(sip, moments), session_for)
    assert result.signal == expected


def test_opposite_sides_do_not_match(session_for: Callable[[datetime], SessionState]) -> None:
    sip = breakout_day(at=29)
    iex = breakout_day(at=29, close=99.2)
    moments = grid(FULL)
    result = compare(turns(iex, moments), turns(sip, moments), session_for)
    assert result.iex_first_minute == result.sip_first_minute
    assert result.signal == SIGNAL_MISMATCH


def test_both_sides_must_share_the_grid(session_for: Callable[[datetime], SessionState]) -> None:
    bars = breakout_day()
    with pytest.raises(ValueError, match="ayni izgarada"):
        compare(turns(bars, grid(range(1, 30))), turns(bars, grid(range(1, 31))), session_for)


def test_a_window_the_bar_size_cannot_tile_is_refused(
    session_for: Callable[[datetime], SessionState],
) -> None:
    bars = breakout_day()
    with pytest.raises(ValueError, match="tam bolunmeli"):
        compare_symbol_day(
            "SPY",
            turns(bars, grid(range(1, 3))),
            turns(bars, grid(range(1, 3))),
            session_for=session_for,
            strategy=STRATEGY,
            opening_range_minutes=7,
            entry_window_minutes=120,
            timeframe=Timeframe.M5,
        )


@pytest.mark.parametrize("reference", [0.0, -1.0, float("nan"), float("inf")])
def test_an_invalid_denominator_gives_no_difference(reference: float) -> None:
    assert _bps(100.0, reference) is None


def test_the_range_status_names_why_there_is_no_difference(
    session_for: Callable[[datetime], SessionState],
) -> None:
    sip = breakout_day(at=29)
    moments = grid(FULL)
    computed = compare(turns(sip, moments), turns(sip, moments), session_for)
    assert computed.range_status == RANGE_COMPUTED
    sip_gap = compare(turns(sip, moments), turns(without_minute(sip, 7), moments), session_for)
    assert (sip_gap.range_status, sip_gap.or_high_bps) == (RANGE_SIP_INCOMPLETE, None)
    sip_missing = compare(turns(sip, moments), [Turn(t, None) for t in moments], session_for)
    assert sip_missing.range_status == RANGE_SIP_MISSING
    iex_gap = compare(turns(without_minute(sip, 7), moments), turns(sip, moments), session_for)
    assert iex_gap.range_status == RANGE_IEX_INCOMPLETE


def test_no_turns_means_everything_is_unknown(
    session_for: Callable[[datetime], SessionState],
) -> None:
    result = compare([], [], session_for)
    assert (result.iex_present, result.signal, result.window_expected) == (
        None,
        SIGNAL_UNKNOWN,
        15,
    )


def test_the_comparison_carries_no_price() -> None:
    """Disari cikan ozet fiyat tasimaz: alanlar sayi, bps, bayrak ve dakikadir."""
    names = {field.name for field in dataclasses.fields(Comparison)}
    assert names == {
        "symbol",
        "window_expected",
        "iex_present",
        "sip_present",
        "iex_completed_later",
        "or_high_bps",
        "or_low_bps",
        "range_status",
        "signal",
        "iex_first_minute",
        "sip_first_minute",
        "iex_unknown_turns",
    }


# --------------------------------------------------------------------------
# Sinirlar
# --------------------------------------------------------------------------


def test_the_core_needs_no_network(
    session_for: Callable[[datetime], SessionState], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise AssertionError("golge cekirdegi ag kullanmamali")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    bars = breakout_day()
    moments = grid(FULL)
    assert compare(turns(bars, moments), turns(bars, moments), session_for).signal == SIGNAL_MATCH


def test_the_core_imports_no_broker_data_or_engine() -> None:
    tree = ast.parse((REPO / "src/tlab/shadow/core.py").read_text(encoding="utf-8"))
    modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden = ("tlab.execution", "tlab.data", "tlab.engine", "tlab.backtest", "alpaca")
    assert not [module for module in modules if module.startswith(forbidden)]
