"""Uzun sureli calisma testi (soak).

Tek bir turun dogru calismasi ile bir seansi bastan sona hatasiz
yurutmek farkli seylerdir. Buradaki testler dongunun yuzlerce turunu
dakika dakika isletiyor ve sonunda DEGISMEZLERI dogruluyor:

  * ayni fikre birden fazla emir gonderilmemis
  * her kapanan islem tam bir kez kaydedilmis
  * kesinlesmemis emir kalmamis
  * her emir bir karara, her islem bir emre bagli
  * gun sonunda pozisyon kalmamis
  * gunler arasi gecis temiz

Bunlar "sistem uzun surede bozulur mu" sorusunun olculebilir hali.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from conftest import make_account, make_bars
from test_runner import FakeBroker, FakeClock, FakeMarket
from tlab.config import Config, load_config
from tlab.core.clock import SimClock
from tlab.core.types import Bar, Fill, OrderRef, Side, Timeframe
from tlab.engine.runner import SessionRunner
from tlab.journal.db import apply_migrations, connect
from tlab.journal.writer import JournalWriter
from tlab.risk.gate import RiskGate
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

SYMBOLS = ("SPY", "AAPL", "MSFT")
SESSION_LENGTH_MINUTES = 390


def session_open_for(day: datetime) -> datetime:
    """O gunun 09:30 New York acilisini UTC olarak verir."""
    return day.replace(hour=14, minute=30, second=0, microsecond=0)


def day_bars(
    open_at: datetime, symbol: str, *, breakout_minute: int | None, base: float
) -> list[Bar]:
    """Bir seansin tamamini kapsayan bar serisi.

    `breakout_minute` verilirse o dakikada hacimli bir kirilim olur;
    verilmezse fiyat gun boyu acilis araligi icinde kalir ve strateji
    hicbir sey yapmaz.
    """
    bars = make_bars(
        SESSION_LENGTH_MINUTES,
        start=open_at,
        symbol=symbol,
        base=base,
        spread=0.5,
        volume=10_000,
    )
    if breakout_minute is None:
        return bars

    broken = bars[breakout_minute]
    bars[breakout_minute] = broken.model_copy(
        update={
            "open": base,
            "close": base + 0.8,
            "high": base + 0.8,
            "low": base - 0.5,
            "volume": 40_000.0,
        }
    )
    # Kirilimdan sonra fiyat yukarida seyreder ki hedefe ulasilabilsin.
    for index in range(breakout_minute + 1, len(bars)):
        bar = bars[index]
        bars[index] = bar.model_copy(
            update={
                "open": base + 1.0,
                "close": base + 1.0,
                "high": base + 1.5,
                "low": base + 0.5,
            }
        )
    return bars


class Simulator:
    """Brokerin zaman icindeki davranisini taklit eder.

    Emirler iki dakika sonra doluyor, pozisyonlar otuz dakika sonra
    hedeften kapaniyor. Amac gercekci bir piyasa modeli degil; amac
    dongunun EMIR -> DOLUM -> KAPANIS yasam dongusunu yuzlerce kez
    dogru yurutup yurutmedigini gormek.
    """

    def __init__(self, broker: FakeBroker, *, fill_delay: int = 2, hold_minutes: int = 30) -> None:
        self.broker = broker
        self.fill_delay = timedelta(minutes=fill_delay)
        self.hold = timedelta(minutes=hold_minutes)
        self._pending: list[tuple[datetime, OrderRef]] = []
        self._held: list[tuple[datetime, OrderRef, float]] = []

    def advance(self, now: datetime) -> None:
        """Simulasyon saatini ilerletir ve emirleri isler."""
        known = {ref.client_order_id for _, ref in self._pending}
        for ref in self.broker.open_orders:
            if ref.client_order_id not in known and not ref.client_order_id.startswith("leg-"):
                self._pending.append((now + self.fill_delay, ref))
                known.add(ref.client_order_id)

        for due, ref in list(self._pending):
            if now < due or ref not in self.broker.open_orders:
                continue
            order = next(
                o for o in self.broker.submitted if o.client_order_id == ref.client_order_id
            )
            price = order.limit_price or 0.0
            self.broker.fill_order(ref, price=price, at=now)
            self._pending.remove((due, ref))
            self._held.append((now + self.hold, ref, order.take_profit))

        for due, ref, target in list(self._held):
            if now < due:
                continue
            order = next(
                o for o in self.broker.submitted if o.client_order_id == ref.client_order_id
            )
            self.broker.fills.append(
                Fill(
                    broker_order_id=f"leg-{ref.broker_order_id}",
                    client_order_id=f"leg-{ref.client_order_id}",
                    symbol=ref.symbol,
                    side=Side.SELL if order.side is Side.BUY else Side.BUY,
                    qty=order.qty,
                    price=target,
                    filled_at=now,
                    order_type="limit",
                )
            )
            self.broker.positions = [p for p in self.broker.positions if p.symbol != ref.symbol]
            self._held.remove((due, ref, target))


@pytest.fixture
def soak_config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text(
        "symbols:\n" + "".join(f"  - {s}\n" for s in SYMBOLS), encoding="utf-8"
    )
    return load_config(project_root)


@pytest.fixture
def soak_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "soak.db")
    apply_migrations(connection)
    yield connection
    connection.close()


def run_session(
    config: Config,
    conn: sqlite3.Connection,
    *,
    day: datetime,
    breakouts: dict[str, int | None],
    account_equity: float = 100_000.0,
) -> tuple[FakeBroker, int]:
    """Bir seansi dakika dakika yurutur; (broker, tur sayisi) doner."""
    open_at = session_open_for(day)
    broker = FakeBroker(
        account=make_account(equity=account_equity, last_equity=100_000.0),
        clock=FakeClock(is_open=True, next_open=open_at, next_close=open_at + timedelta(hours=6.5)),
    )
    market = FakeMarket(
        bars_by_symbol={
            symbol: day_bars(open_at, symbol, breakout_minute=minute, base=100.0 + index * 10)
            for index, (symbol, minute) in enumerate(breakouts.items())
        }
    )
    simulator = Simulator(broker)

    clock = SimClock(open_at - timedelta(minutes=5))
    writer = JournalWriter(conn, clock)
    run_id = writer.start_run(
        mode="backtest", data_feed="iex", params_version="orb-soak", config={}
    )
    runner = SessionRunner(
        broker=broker,
        market=market,
        strategies=[OpeningRangeBreakout(ORBParams())],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
        run_id=run_id,
        timeframe=Timeframe.M1,
        entry_order_ttl_minutes=config.session.entry_order_ttl_minutes,
    )

    turns = 0
    for minute in range(-5, SESSION_LENGTH_MINUTES + 5):
        clock.set(open_at + timedelta(minutes=minute))
        # Broker emri aldigi anda damgalar; sabit bir zaman damgasi
        # emirleri dogduklari anda "bayat" gosterirdi.
        broker.submitted_at = clock.now()
        simulator.advance(clock.now())
        market.quote_mid = 100.0
        runner.run_once()
        turns += 1

    writer.end_run(run_id)
    return broker, turns


# --------------------------------------------------------------------------
# Testler
# --------------------------------------------------------------------------


def test_full_session_runs_without_losing_its_footing(
    soak_config: Config, soak_conn: sqlite3.Connection
) -> None:
    """400 tur: emir yasam dongusu bastan sona tutarli kalmali."""
    broker, turns = run_session(
        soak_config,
        soak_conn,
        day=datetime(2026, 1, 5, tzinfo=UTC),
        breakouts={"SPY": 20, "AAPL": 60, "MSFT": None},
    )

    assert turns == SESSION_LENGTH_MINUTES + 10

    orders = soak_conn.execute("SELECT symbol, status FROM orders").fetchall()
    symbols = [row["symbol"] for row in orders]
    # Kirilim yapan iki sembol, her biri icin TEK emir.
    assert sorted(symbols) == ["AAPL", "SPY"]
    assert "MSFT" not in symbols, "kirilim olmayan sembole emir gonderilmemeli"

    # Kesinlesmemis emir kalmamali: hepsi ya kesinlesti ya kapandi.
    assert not [row for row in orders if row["status"] == "submitting"]

    trades = soak_conn.execute("SELECT * FROM trades").fetchall()
    assert len(trades) == 2
    assert {row["symbol"] for row in trades} == {"SPY", "AAPL"}
    assert all(row["net_pnl"] > 0 for row in trades), "hedeften kapanan islem kar yazmali"

    # Gun sonunda acik pozisyon kalmamali.
    assert broker.positions == []


def test_no_duplicate_trades_across_hundreds_of_reconciliations(
    soak_config: Config, soak_conn: sqlite3.Connection
) -> None:
    """Mutabakat her turda calisiyor; kayit yine de tek olmali."""
    run_session(
        soak_config,
        soak_conn,
        day=datetime(2026, 1, 5, tzinfo=UTC),
        breakouts={"SPY": 20, "AAPL": 60, "MSFT": None},
    )
    total = soak_conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
    distinct = soak_conn.execute("SELECT COUNT(DISTINCT trade_id) AS n FROM trades").fetchone()["n"]
    assert total == distinct == 2

    fills_total = soak_conn.execute("SELECT COUNT(*) AS n FROM fills").fetchone()["n"]
    fills_distinct = soak_conn.execute(
        "SELECT COUNT(DISTINCT broker_order_id) AS n FROM fills"
    ).fetchone()["n"]
    assert fills_total == fills_distinct


def test_journal_stays_referentially_consistent(
    soak_config: Config, soak_conn: sqlite3.Connection
) -> None:
    """Her emir bir karara, her islem bir emre baglanabilmeli.

    Bu zincir kopuk olursa kapanan bir pozisyon hicbir stratejiye
    atfedilemez ve ogrenme katmani o islemi kullanamaz.
    """
    run_session(
        soak_config,
        soak_conn,
        day=datetime(2026, 1, 5, tzinfo=UTC),
        breakouts={"SPY": 20, "AAPL": 60, "MSFT": None},
    )

    orphan_orders = soak_conn.execute(
        "SELECT COUNT(*) AS n FROM orders o"
        " LEFT JOIN decisions d ON d.decision_id = o.decision_id"
        " WHERE d.decision_id IS NULL"
    ).fetchone()["n"]
    assert orphan_orders == 0

    orphan_trades = soak_conn.execute(
        "SELECT COUNT(*) AS n FROM trades t"
        " LEFT JOIN decisions d ON d.decision_id = t.decision_id"
        " WHERE d.decision_id IS NULL"
    ).fetchone()["n"]
    assert orphan_trades == 0

    unattributed = soak_conn.execute(
        "SELECT COUNT(*) AS n FROM trades WHERE strategy_id = 'unknown'"
    ).fetchone()["n"]
    assert unattributed == 0


def test_journal_growth_is_proportional_to_activity(
    soak_config: Config, soak_conn: sqlite3.Connection
) -> None:
    """400 tur donen bir dongu, 400 kayit birakmamali.

    Karar kaydi her turda degil, strateji bir NIYET urettiginde
    dusuyor. Aksi halde journal gunde binlerce anlamsiz satirla
    sisip ogrenme sorgularini yavaslatirdi.
    """
    run_session(
        soak_config,
        soak_conn,
        day=datetime(2026, 1, 5, tzinfo=UTC),
        breakouts={"SPY": 20, "AAPL": 60, "MSFT": None},
    )
    decisions = soak_conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
    assert 0 < decisions <= 10, f"beklenenden cok karar kaydi: {decisions}"


def test_consecutive_days_stay_independent(
    soak_config: Config, soak_conn: sqlite3.Connection
) -> None:
    """Iki gun ust uste: ikinci gun birincinin durumundan etkilenmemeli."""
    run_session(
        soak_config,
        soak_conn,
        day=datetime(2026, 1, 5, tzinfo=UTC),
        breakouts={"SPY": 20, "AAPL": None, "MSFT": None},
    )
    first_day_trades = soak_conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]

    run_session(
        soak_config,
        soak_conn,
        day=datetime(2026, 1, 6, tzinfo=UTC),
        breakouts={"SPY": 25, "AAPL": None, "MSFT": None},
    )
    total = soak_conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]

    assert first_day_trades == 1
    assert total == 2, "ikinci gun kendi islemini acabilmeli"


def test_kill_switch_day_produces_no_orders_at_all(
    soak_config: Config, soak_conn: sqlite3.Connection
) -> None:
    """Zararda baslayan bir gunde dongu 400 tur donse de islem acmamali."""
    broker, _ = run_session(
        soak_config,
        soak_conn,
        day=datetime(2026, 1, 5, tzinfo=UTC),
        breakouts={"SPY": 20, "AAPL": 60, "MSFT": None},
        account_equity=97_000.0,
    )
    assert broker.submitted == []
    assert soak_conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"] == 0

    halts = soak_conn.execute("SELECT COUNT(*) AS n FROM daily_state").fetchone()["n"]
    assert halts == 1, "gun bir kez kapatilmali, her turda degil"


def test_quotes_and_bars_are_requested_without_future_data(
    soak_config: Config, soak_conn: sqlite3.Connection
) -> None:
    """Strateji hicbir turda henuz olusmamis bir barla karar vermemeli.

    Kirilim 20. dakikada; ondan once emir cikmasi, gelecege bakildigi
    anlamina gelirdi.
    """
    run_session(
        soak_config,
        soak_conn,
        day=datetime(2026, 1, 5, tzinfo=UTC),
        breakouts={"SPY": 20, "AAPL": None, "MSFT": None},
    )
    row = soak_conn.execute(
        "SELECT ts FROM decisions WHERE symbol = 'SPY' ORDER BY ts LIMIT 1"
    ).fetchone()
    assert row is not None
    first_decision = datetime.fromisoformat(str(row["ts"]))
    breakout_at = session_open_for(datetime(2026, 1, 5, tzinfo=UTC)) + timedelta(minutes=20)
    assert first_decision >= breakout_at + timedelta(minutes=1)
