"""Golge broker (docs/designs/shadow-observation.md §1, §3).

Iki sey gosterilir:

  * ShadowBroker hesap ve emir yoluna dokunmaz: okumalar sentetik ya
    da bos, yazmalar hata, saat takvimden.
  * Canli dongu (`--dry-run`) bu broker ve kaydeden veri kaynagiyla
    calistiginda, her turdaki niyeti saf karar yolunun AYNI turdaki
    kayitli gorunumden urettigi niyetle ayni. Farkli olsaydi bu bir kod
    bulgusu olurdu, feed bulgusu degil.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from conftest import SESSION_OPEN, make_bars, make_quote
from tlab.config import Config, load_config
from tlab.core.calendar import TradingSession
from tlab.core.clock import SimClock
from tlab.core.types import Bar, Intent, Quote, Side, Timeframe
from tlab.engine.runner import SessionRunner
from tlab.errors import BrokerError
from tlab.journal.db import apply_migrations, connect
from tlab.journal.writer import JournalWriter
from tlab.risk.gate import RiskGate
from tlab.shadow.broker import REFUSAL, ShadowBroker
from tlab.shadow.core import (
    SYNTHETIC_ACCOUNT,
    RecordingStrategy,
    intent_at,
    live_pure_mismatches,
    normalized,
    session_at,
    visible_bars,
)
from tlab.shadow.record import RecordingMarket, SeenRecord
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

CLOSE = SESSION_OPEN + timedelta(hours=6, minutes=30)
MONDAY = TradingSession(day=date(2026, 1, 5), open=SESSION_OPEN, close=CLOSE)
TUESDAY = TradingSession(
    day=date(2026, 1, 6), open=SESSION_OPEN + timedelta(days=1), close=CLOSE + timedelta(days=1)
)
EARLY = TradingSession(
    day=date(2026, 1, 7),
    open=SESSION_OPEN + timedelta(days=2),
    close=SESSION_OPEN + timedelta(days=2, hours=3, minutes=30),
)


def shadow(now: datetime, sessions: tuple[TradingSession, ...] = (MONDAY, TUESDAY)) -> ShadowBroker:
    return ShadowBroker(sessions, SimClock(now))


# --------------------------------------------------------------------------
# Okuma ve yazma
# --------------------------------------------------------------------------


def test_reads_are_synthetic_or_empty() -> None:
    broker = shadow(SESSION_OPEN)
    assert broker.get_account() is SYNTHETIC_ACCOUNT
    assert broker.get_positions() == []
    assert broker.list_open_orders() == []
    assert broker.list_fills(SESSION_OPEN - timedelta(days=1)) == []


@pytest.mark.parametrize(
    ("method", "args"),
    [("submit_bracket", (object(),)), ("close_position", ("SPY",)), ("cancel_open_orders", ())],
)
def test_writes_fail_fast(method: str, args: tuple[Any, ...]) -> None:
    with pytest.raises(BrokerError, match=REFUSAL):
        getattr(shadow(SESSION_OPEN), method)(*args)


def test_the_broker_holds_no_network_client() -> None:
    broker = shadow(SESSION_OPEN)
    assert set(vars(broker)) == {"sessions", "clock"}


def test_a_broker_without_a_calendar_is_refused() -> None:
    with pytest.raises(BrokerError, match="takvimsiz"):
        ShadowBroker((), SimClock(SESSION_OPEN))


# --------------------------------------------------------------------------
# Saat: takvimden
# --------------------------------------------------------------------------


def test_before_the_open_the_market_is_closed() -> None:
    clock = shadow(SESSION_OPEN - timedelta(minutes=20)).get_market_clock()
    assert (clock.is_open, clock.next_open, clock.next_close) == (False, SESSION_OPEN, CLOSE)


def test_during_the_session_the_market_is_open() -> None:
    clock = shadow(SESSION_OPEN + timedelta(minutes=30)).get_market_clock()
    assert (clock.is_open, clock.next_open, clock.next_close) == (True, TUESDAY.open, CLOSE)


def test_at_the_close_the_next_session_is_announced() -> None:
    clock = shadow(CLOSE).get_market_clock()
    assert (clock.is_open, clock.next_open) == (False, TUESDAY.open)


def test_an_early_close_comes_from_the_calendar() -> None:
    now = EARLY.open + timedelta(hours=1)
    clock = shadow(
        now,
        (
            MONDAY,
            TUESDAY,
            EARLY,
            MONDAY.model_copy(
                update={
                    "day": date(2026, 1, 8),
                    "open": SESSION_OPEN + timedelta(days=3),
                    "close": CLOSE + timedelta(days=3),
                }
            ),
        ),
    ).get_market_clock()
    assert clock.is_open
    assert clock.next_close == EARLY.close


@pytest.mark.parametrize(
    "now",
    [CLOSE + timedelta(days=1), TUESDAY.open + timedelta(minutes=5)],
    ids=["calendar-ended", "no-next-session"],
)
def test_a_moment_the_calendar_cannot_place_is_an_error(now: datetime) -> None:
    with pytest.raises(BrokerError, match="takvim"):
        shadow(now).get_market_clock()


# --------------------------------------------------------------------------
# Canli dongu: emirsiz ve saf yolla tutarli
# --------------------------------------------------------------------------


@dataclass
class Market:
    bars_by_symbol: dict[str, list[Bar]]
    requests: list[tuple[str, datetime, datetime | None]] = field(default_factory=list)

    def bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime | None = None
    ) -> list[Bar]:
        self.requests.append((symbol, start, end))
        return [
            bar
            for bar in self.bars_by_symbol.get(symbol, [])
            if bar.ts >= start and (end is None or bar.ts <= end)
        ]

    def latest_quote(self, symbol: str) -> Quote:
        return make_quote(symbol, mid=100.8)


class Spy(ShadowBroker):
    """Yazma yoluna girilirse kaydeder (ve yine reddeder)."""

    def __init__(self, sessions: tuple[TradingSession, ...], clock: SimClock) -> None:
        super().__init__(sessions, clock)
        self.writes: list[str] = []

    def submit_bracket(self, order: Any) -> Any:
        self.writes.append("submit_bracket")
        return super().submit_bracket(order)

    def close_position(self, symbol: str) -> Any:
        self.writes.append("close_position")
        return super().close_position(symbol)

    def cancel_open_orders(self, symbol: str | None = None) -> int:
        self.writes.append("cancel_open_orders")
        return super().cancel_open_orders(symbol)


@pytest.fixture
def config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text(
        "symbols:\n  - SPY\n  - AAPL\n", encoding="utf-8"
    )
    return load_config(project_root)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    apply_migrations(connection)
    yield connection
    connection.close()


def day_bars(symbol: str, *, breakout_at: int | None, base: float) -> list[Bar]:
    """Bir onceki gun ve bu seans; `breakout_at` dakikasinda yukari kirilim."""
    history = make_bars(60, start=SESSION_OPEN - timedelta(days=1), symbol=symbol, base=base)
    today = make_bars(90, symbol=symbol, base=base, spread=0.5, volume=10_000)
    if breakout_at is not None:
        close = base + 0.8
        today[breakout_at] = today[breakout_at].model_copy(
            update={
                "open": base,
                "close": close,
                "high": close,
                "low": base - 0.5,
                "volume": 30_000.0,
            }
        )
    return history + today


def test_the_dry_run_loop_matches_the_pure_path_turn_by_turn(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Her niyet birebir: sembol, an ve normallestirilmis alanlar.

    Toplam sayi yetmez (Codex 6154024443). Canli dongunun baglaminda
    kotasyon var, saf yolda yok; kotasyondan tureyen ozellik bu yuzden
    karsilastirma disinda ve canli tarafta gercekten bulunuyor.
    """
    params = ORBParams()
    live = RecordingStrategy(OpeningRangeBreakout(params))
    market = Market(
        {
            "SPY": day_bars("SPY", breakout_at=40, base=100.0),
            "AAPL": day_bars("AAPL", breakout_at=None, base=200.0),
        }
    )
    clock = SimClock(SESSION_OPEN - timedelta(minutes=5))
    record = SeenRecord(sqlite3.connect(":memory:"))
    broker = Spy((MONDAY, TUESDAY), clock)
    writer = JournalWriter(conn, clock)
    run_id = writer.start_run(mode="paper", data_feed="iex", params_version="orb", config={})
    runner = SessionRunner(
        broker=broker,
        market=RecordingMarket(market, record, clock),
        strategies=[live],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
        run_id=run_id,
        dry_run=True,
    )
    for minute in range(-5, 75):
        clock.set(SESSION_OPEN + timedelta(minutes=minute, seconds=7))
        runner.run_once()

    assert broker.writes == []
    assert live.seen, "canli dongu en az bir niyet uretmeli"
    assert all("spread_bps" in intent.features for _, _, intent in live.seen)

    pure = []
    strategy = OpeningRangeBreakout(params)
    for symbol in ("SPY", "AAPL"):
        for moment in record.moments(symbol):
            seen = record.view(symbol, moment)
            assert seen is not None
            bars = visible_bars(seen, moment, timeframe=Timeframe.M1, history_days=3)
            session = session_at(
                moment,
                config=config,
                opening_range_minutes=params.opening_range_minutes,
                market_close=MONDAY.close,
            )
            intent = intent_at(symbol, bars, session, strategy=strategy, timeframe=Timeframe.M1)
            if intent is not None:
                pure.append((moment, symbol, intent))

    assert [(m, s) for m, s, _ in pure] == [(m, s) for m, s, _ in live.seen]
    assert [normalized(i) for _, _, i in pure] == [normalized(i) for _, _, i in live.seen]
    assert live_pure_mismatches(live.seen, pure) == 0


def test_a_field_difference_is_a_mismatch_even_with_equal_counts() -> None:
    moment = SESSION_OPEN + timedelta(minutes=41, seconds=7)
    base = Intent(
        strategy_id="orb",
        symbol="SPY",
        side=Side.BUY,
        reference_price=100.8,
        stop_loss=100.0,
        take_profit=102.4,
        features={"atr": 0.5, "spread_bps": 2.0},
    )
    quote_only = base.model_copy(update={"features": {"atr": 0.5}})
    other_stop = base.model_copy(update={"stop_loss": 99.9})
    assert live_pure_mismatches([(moment, "SPY", base)], [(moment, "SPY", quote_only)]) == 0
    assert live_pure_mismatches([(moment, "SPY", base)], [(moment, "SPY", other_stop)]) == 1
    later = moment + timedelta(minutes=1)
    assert live_pure_mismatches([(moment, "SPY", base)], [(later, "SPY", base)]) == 2
    assert live_pure_mismatches([(moment, "SPY", base)], []) == 1


def test_the_recorder_does_not_change_decisions() -> None:
    inner = OpeningRangeBreakout(ORBParams())
    wrapped = RecordingStrategy(inner)
    assert (wrapped.strategy_id, wrapped.params_version) == (
        inner.strategy_id,
        inner.params_version,
    )


def test_the_loop_reads_no_account_state_from_elsewhere(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Hesap degeri sentetik: journal'a yazilan karar boyutu sentetik hesaptan."""
    clock = SimClock(SESSION_OPEN + timedelta(minutes=41, seconds=7))
    writer = JournalWriter(conn, clock)
    run_id = writer.start_run(mode="paper", data_feed="iex", params_version="orb", config={})
    runner = SessionRunner(
        broker=Spy((MONDAY, TUESDAY), clock),
        market=Market({"SPY": day_bars("SPY", breakout_at=40, base=100.0)}),
        strategies=[OpeningRangeBreakout(ORBParams())],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
        run_id=run_id,
        dry_run=True,
    )
    result = runner.run_once()
    assert result.intents == 1
    assert result.submitted == 0
