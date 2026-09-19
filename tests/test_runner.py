"""Seans dongusunun ucтан uca testi.

Sahte bir broker ve sahte veri kaynagiyla, sistemin tamami ag
erisimi olmadan calistiriliyor: strateji, risk kapisi, emir
gonderimi, journal kaydi ve mutabakat birlikte.

Bu testin var olabilmesi mimarinin dogru katmanlandiginin kanitidir:
Broker ve MarketData birer protokol oldugu icin, ustteki hicbir kod
altinda Alpaca mi yoksa sahte bir nesne mi oldugunu bilmiyor.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import SESSION_OPEN, make_account, make_bars, make_quote
from tlab.config import Config, load_config
from tlab.core.clock import SimClock
from tlab.core.types import (
    Account,
    Bar,
    BracketOrder,
    Fill,
    OrderRef,
    Position,
    Quote,
    Side,
    Timeframe,
)
from tlab.engine.runner import SessionRunner
from tlab.errors import DataError
from tlab.journal.db import apply_migrations, connect
from tlab.journal.writer import JournalWriter
from tlab.risk.gate import RiskGate
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

NOW = SESSION_OPEN + timedelta(minutes=30)


# --------------------------------------------------------------------------
# Sahteler
# --------------------------------------------------------------------------


@dataclass
class FakeClock:
    is_open: bool = True
    next_open: datetime = SESSION_OPEN
    next_close: datetime = SESSION_OPEN + timedelta(hours=6, minutes=30)


@dataclass
class FakeBroker:
    """Broker protokolunu uygulayan sahte broker."""

    account: Account = field(default_factory=make_account)
    positions: list[Position] = field(default_factory=list)
    clock: FakeClock = field(default_factory=FakeClock)
    fills: list[Fill] = field(default_factory=list)

    submitted: list[BracketOrder] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    cancelled: list[str | None] = field(default_factory=list)

    def get_account(self) -> Account:
        return self.account

    def get_positions(self) -> list[Position]:
        return list(self.positions)

    def get_market_clock(self) -> FakeClock:
        return self.clock

    def list_open_orders(self) -> list[OrderRef]:
        return []

    def list_fills(self, since: datetime) -> list[Fill]:
        return [f for f in self.fills if f.filled_at >= since]

    def submit_bracket(self, order: BracketOrder) -> OrderRef:
        self.submitted.append(order)
        return OrderRef(
            broker_order_id=f"broker-{len(self.submitted)}",
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            submitted_at=NOW,
            status="accepted",
        )

    def close_position(self, symbol: str) -> OrderRef | None:
        self.closed.append(symbol)
        return OrderRef(
            broker_order_id=f"close-{symbol}",
            client_order_id=f"close-{symbol}",
            symbol=symbol,
            submitted_at=NOW,
            status="filled",
        )

    def cancel_open_orders(self, symbol: str | None = None) -> int:
        self.cancelled.append(symbol)
        return 0


@dataclass
class FakeMarket:
    """MarketData protokolunu uygulayan sahte veri kaynagi."""

    bars_by_symbol: dict[str, list[Bar]] = field(default_factory=dict)
    quote_mid: float = 100.8
    failing_symbols: set[str] = field(default_factory=set)

    def bars(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime | None = None
    ) -> list[Bar]:
        if symbol in self.failing_symbols:
            msg = f"{symbol} icin veri yok"
            raise DataError(msg)
        return list(self.bars_by_symbol.get(symbol, []))

    def latest_quote(self, symbol: str) -> Quote:
        if symbol in self.failing_symbols:
            msg = f"{symbol} icin kotasyon yok"
            raise DataError(msg)
        return make_quote(symbol, mid=self.quote_mid)


def breakout_bars(symbol: str = "SPY", close: float = 100.8) -> list[Bar]:
    """Acilis araligi olusmus ve yukari kirilmis bir seans."""
    bars = make_bars(30, symbol=symbol, base=100.0, spread=0.5, volume=10_000)
    bars[-1] = bars[-1].model_copy(
        update={"open": 100.0, "close": close, "high": close, "low": 99.5, "volume": 30_000.0}
    )
    return bars


# --------------------------------------------------------------------------
# Kurulum
# --------------------------------------------------------------------------


@pytest.fixture
def config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text("symbols:\n  - SPY\n", encoding="utf-8")
    return load_config(project_root)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "journal.db")
    apply_migrations(connection)
    yield connection
    connection.close()


def build_runner(
    *,
    config: Config,
    conn: sqlite3.Connection,
    broker: FakeBroker,
    market: FakeMarket,
    dry_run: bool = False,
    now: datetime = NOW,
) -> SessionRunner:
    writer = JournalWriter(conn)
    run_id = writer.start_run(
        mode="backtest", data_feed="iex", params_version="orb-test", config={}
    )
    return SessionRunner(
        broker=broker,  # type: ignore[arg-type]
        market=market,  # type: ignore[arg-type]
        strategies=[OpeningRangeBreakout(ORBParams())],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=SimClock(now),
        run_id=run_id,
        dry_run=dry_run,
    )


# --------------------------------------------------------------------------
# Testler
# --------------------------------------------------------------------------


def test_full_loop_submits_a_bracket_order(config: Config, conn: sqlite3.Connection) -> None:
    """Strateji, risk kapisi, emir ve journal birlikte calisiyor."""
    broker = FakeBroker()
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)

    result = runner.run_once()

    assert result.evaluated == 1
    assert result.intents == 1
    assert result.submitted == 1
    assert len(broker.submitted) == 1

    order = broker.submitted[0]
    assert order.symbol == "SPY"
    assert order.side is Side.BUY
    assert order.stop_loss < (order.limit_price or 0) < order.take_profit

    row = conn.execute("SELECT * FROM decisions").fetchone()
    assert row["allowed"] == 1
    assert row["qty"] == order.qty
    stored = conn.execute("SELECT * FROM orders").fetchone()
    # Emir BIR KEZ uretilmeli: journal'daki kimlik brokera gidenle ayni.
    assert stored["client_order_id"] == order.client_order_id
    assert stored["decision_id"] == row["decision_id"]


def test_dry_run_records_decisions_without_sending_orders(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Ilk calistirmada sistemin ne yapacagi once gozlemlenebilmeli."""
    broker = FakeBroker()
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(config=config, conn=conn, broker=broker, market=market, dry_run=True)

    result = runner.run_once()

    assert result.intents == 1
    assert result.submitted == 0
    assert broker.submitted == []
    assert conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"] == 0


def test_closed_market_does_nothing(config: Config, conn: sqlite3.Connection) -> None:
    """Tatil gunlerini broker biliyor; biz takvim tahmin etmiyoruz."""
    broker = FakeBroker(clock=FakeClock(is_open=False))
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    result = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert result.evaluated == 0
    assert broker.submitted == []
    assert "borsa kapali" in " ".join(result.notes)


def test_kill_switch_flattens_and_halts_for_the_day(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Gun kotuye gittiginde stratejinin ne dusundugunun onemi yok."""
    position = Position(
        symbol="AAPL", side=Side.BUY, qty=10, avg_entry_price=100.0, current_price=95.0
    )
    broker = FakeBroker(
        account=make_account(equity=97_000, last_equity=100_000), positions=[position]
    )
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)

    result = runner.run_once()
    assert result.halted
    assert result.flattened == 1
    assert broker.closed == ["AAPL"]
    assert broker.submitted == []
    assert "KILL-SWITCH" in " ".join(result.notes)

    # Hesap toparlansa bile gun yeniden acilmaz.
    broker.account = make_account(equity=100_000, last_equity=100_000)
    broker.positions = []
    second = runner.run_once()
    assert second.halted
    assert broker.submitted == []


def test_flatten_window_closes_positions(config: Config, conn: sqlite3.Connection) -> None:
    """Kapanisa dakikalar kala pozisyon acilmaz, acik olanlar kapatilir."""
    position = Position(
        symbol="SPY", side=Side.BUY, qty=10, avg_entry_price=100.0, current_price=101.0
    )
    broker = FakeBroker(positions=[position])
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(
        config=config,
        conn=conn,
        broker=broker,
        market=market,
        now=SESSION_OPEN + timedelta(minutes=385),
    )

    result = runner.run_once()
    assert result.flattened == 1
    assert broker.closed == ["SPY"]
    # Emirler pozisyondan ONCE iptal edilmeli: sahipsiz kalan bir
    # bracket bacagi ters yonde yeni pozisyon acabilir.
    assert broker.cancelled == ["SPY"]
    assert broker.submitted == []


def test_forming_bar_is_excluded(config: Config, conn: sqlite3.Connection) -> None:
    """Kapanmamis barin kapanisini karara katmak gelecegi bilmektir."""
    bars = breakout_bars()
    # Son bar 14:59'da acilir, 15:00'te kapanir. Saati 14:59'a alinca
    # bu bar henuz olusuyor demektir ve kirilim gorulmemeli.
    runner = build_runner(
        config=config,
        conn=conn,
        broker=FakeBroker(),
        market=FakeMarket(bars_by_symbol={"SPY": bars}),
        now=SESSION_OPEN + timedelta(minutes=29, seconds=30),
    )
    assert runner.run_once().intents == 0


def test_data_failure_on_one_symbol_does_not_stop_the_loop(
    project_root: Path, conn: sqlite3.Connection
) -> None:
    """Veri gelmeyen bir hisse yuzunden tum seansi kaybetmek kabul edilemez."""
    (project_root / "config" / "universe.yaml").write_text(
        "symbols:\n  - BROKEN\n  - SPY\n", encoding="utf-8"
    )
    config = load_config(project_root)
    broker = FakeBroker()
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()}, failing_symbols={"BROKEN"})
    result = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert result.evaluated == 1  # BROKEN atlandi, SPY degerlendirildi
    assert result.submitted == 1


def test_vetoed_decision_is_recorded_with_reasons(config: Config, conn: sqlite3.Connection) -> None:
    """Yapilmayan islemler de ogrenme icin kaydedilir.

    Strateji niyet uretiyor, risk kapisi PDT siniri yuzunden veto
    ediyor. Kayit yine de dusuyor: 'kapi engellemeseydi ne olurdu'
    sorusu ancak boyle cevaplanabilir.
    """
    broker = FakeBroker(account=make_account(equity=20_000, daytrade_count=3))
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    result = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert result.intents == 1
    assert result.vetoed == 1
    assert result.submitted == 0
    assert broker.submitted == []

    row = conn.execute("SELECT * FROM decisions").fetchone()
    assert row["allowed"] == 0
    assert row["qty"] == 0
    assert "PDT siniri" in row["veto_reasons"]
    # Ozellik fotografi veto edilen kararlarda da saklanir.
    assert "rvol" in row["features_json"]


def test_reconciliation_records_a_closed_trade(config: Config, conn: sqlite3.Connection) -> None:
    """Sistem kapaliyken tetiklenen bir stop bile acilista kayda gecer."""
    broker = FakeBroker()
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)

    runner.run_once()
    order = broker.submitted[0]

    # Giris ve hedef bacagi dolmus gibi davran.
    broker.fills = [
        Fill(
            broker_order_id="broker-1",
            client_order_id=order.client_order_id,
            symbol="SPY",
            side=Side.BUY,
            qty=order.qty,
            price=order.limit_price or 100.8,
            filled_at=NOW,
            order_type="limit",
        ),
        Fill(
            broker_order_id="leg-target",
            client_order_id="leg-target",
            symbol="SPY",
            side=Side.SELL,
            qty=order.qty,
            price=order.take_profit,
            filled_at=NOW + timedelta(minutes=20),
            order_type="limit",
        ),
    ]
    broker.positions = []

    second = runner.run_once()
    assert second.trades_recorded == 1

    trade = conn.execute("SELECT * FROM trades").fetchone()
    assert trade["symbol"] == "SPY"
    assert trade["exit_reason"] == "target"
    assert trade["r_multiple"] == pytest.approx(1.5, abs=0.02)
    assert trade["net_pnl"] > 0

    # Ucuncu tur ayni islemi yeniden yazmamali.
    assert runner.run_once().trades_recorded == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"] == 1


def test_loop_result_summary_is_readable(config: Config, conn: sqlite3.Connection) -> None:
    runner = build_runner(
        config=config,
        conn=conn,
        broker=FakeBroker(),
        market=FakeMarket(bars_by_symbol={"SPY": breakout_bars()}),
    )
    summary = runner.run_once().summary()
    assert "emir=1" in summary
    assert "borsa=acik" in summary
