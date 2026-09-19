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
import uuid
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
from tlab.errors import BrokerError, DataError
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
    """Broker protokolunu uygulayan sahte broker.

    Gonderilen emirleri BEKLEYEN olarak tutuyor. Bu ayrinti onemli:
    gercek brokerda bir limit emri dolana kadar bekler ve o sure
    boyunca ortada pozisyon YOKTUR. Emri unutan bir sahte broker,
    tam da bu penceredeki hatalari gizler.
    """

    account: Account = field(default_factory=make_account)
    positions: list[Position] = field(default_factory=list)
    clock: FakeClock = field(default_factory=FakeClock)
    fills: list[Fill] = field(default_factory=list)

    submitted: list[BracketOrder] = field(default_factory=list)
    open_orders: list[OrderRef] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    cancelled: list[str | None] = field(default_factory=list)
    fail_open_orders: bool = False
    fail_submit: bool = False
    submitted_at: datetime = NOW
    """Brokerin emri aldigi an. Cagiran taraf zamani ilerletiyorsa
    her turda guncellenmeli; sabit birakilirsa emirler dogduklari
    anda bayat gorunur."""

    def get_account(self) -> Account:
        return self.account

    def get_positions(self) -> list[Position]:
        return list(self.positions)

    def get_market_clock(self) -> FakeClock:
        return self.clock

    def list_open_orders(self) -> list[OrderRef]:
        if self.fail_open_orders:
            msg = "bekleyen emirler alinamadi"
            raise BrokerError(msg)
        return list(self.open_orders)

    def list_fills(self, since: datetime) -> list[Fill]:
        return [f for f in self.fills if f.filled_at >= since]

    def submit_bracket(self, order: BracketOrder) -> OrderRef:
        if self.fail_submit:
            msg = "emir gonderilemedi"
            raise BrokerError(msg)
        self.submitted.append(order)
        ref = OrderRef(
            # Gercek broker kimlik tekrar etmez. Sayaca dayali bir
            # kimlik, ayni veritabanini paylasan iki kosuda cakisir
            # ve olmayan bir hata gibi gorunur.
            broker_order_id=f"broker-{uuid.uuid4().hex[:12]}",
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            submitted_at=self.submitted_at,
            status="accepted",
        )
        self.open_orders.append(ref)
        return ref

    def close_position(self, symbol: str) -> OrderRef | None:
        self.closed.append(symbol)
        self.positions = [p for p in self.positions if p.symbol != symbol]
        return OrderRef(
            broker_order_id=f"close-{symbol}",
            client_order_id=f"close-{symbol}",
            symbol=symbol,
            submitted_at=NOW,
            status="filled",
        )

    def cancel_open_orders(self, symbol: str | None = None) -> int:
        self.cancelled.append(symbol)
        before = len(self.open_orders)
        self.open_orders = [
            o for o in self.open_orders if symbol is not None and o.symbol != symbol
        ]
        return before - len(self.open_orders)

    def fill_order(self, ref: OrderRef, price: float, at: datetime) -> None:
        """Bekleyen bir emri dolmus gibi isaretler."""
        self.open_orders = [o for o in self.open_orders if o.client_order_id != ref.client_order_id]
        order = next(o for o in self.submitted if o.client_order_id == ref.client_order_id)
        self.fills.append(
            Fill(
                broker_order_id=ref.broker_order_id,
                client_order_id=ref.client_order_id,
                symbol=ref.symbol,
                side=order.side,
                qty=order.qty,
                price=price,
                filled_at=at,
                order_type="limit",
            )
        )
        self.positions.append(
            Position(
                symbol=ref.symbol,
                side=order.side,
                qty=order.qty,
                avg_entry_price=price,
                current_price=price,
            )
        )


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
        # Tarih araligi gercek kaynaktaki gibi uygulaniyor: aksi halde
        # sahte veri, o anda HENUZ OLUSMAMIS barlari da dondururdu ve
        # testler gercekte imkansiz bir bilgiyle calisirdi.
        return [
            bar
            for bar in self.bars_by_symbol.get(symbol, [])
            if bar.ts >= start and (end is None or bar.ts <= end)
        ]

    def latest_quote(self, symbol: str) -> Quote:
        if symbol in self.failing_symbols:
            msg = f"{symbol} icin kotasyon yok"
            raise DataError(msg)
        return make_quote(symbol, mid=self.quote_mid)


def breakout_bars_at(start: datetime, symbol: str = "SPY", close: float = 100.8) -> list[Bar]:
    """Belirli bir seans acilisindan baslayan kirilim serisi."""
    bars = make_bars(30, start=start, symbol=symbol, base=100.0, spread=0.5, volume=10_000)
    bars[-1] = bars[-1].model_copy(
        update={"open": 100.0, "close": close, "high": close, "low": 99.5, "volume": 30_000.0}
    )
    return bars


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
    clock = SimClock(now)
    writer = JournalWriter(conn, clock)
    run_id = writer.start_run(
        mode="backtest", data_feed="iex", params_version="orb-test", config={}
    )
    return SessionRunner(
        # Burada bilincli olarak hicbir tip bastirmasi yok: FakeBroker
        # ile FakeMarket, Broker ve MarketData protokollerine yapisal
        # olarak uyuyor. Protokol degisip de sahteler geride kalirsa
        # mypy tam bu satirda duruyor.
        broker=broker,
        market=market,
        strategies=[OpeningRangeBreakout(ORBParams())],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
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


# --------------------------------------------------------------------------
# Uzun sureli calisma dayanikliligi
# --------------------------------------------------------------------------
#
# Buradaki testler tek bir soruyu kovaliyor: dongu saatlerce, gunlerce
# donerken ne bozulur? Hepsi gercekten gozlemlenmis kusurlarin
# regresyon testi.


def test_unfilled_order_does_not_trigger_a_second_order(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Dolmayi bekleyen bir emrin uzerine ikincisi gonderilmemeli.

    Limit emri dolana kadar ortada POZISYON YOKTUR. Yalnizca pozisyon
    listesine bakan bir dongu, emri unutup her turda yenisini gonderir:
    bir saat dolmayan emir 60 kat pozisyon demek.
    """
    broker = FakeBroker()
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)

    for _ in range(10):
        runner.run_once()

    assert len(broker.submitted) == 1
    assert len(broker.open_orders) == 1


def test_pending_order_blocks_entry_even_without_a_journal_record(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Brokerdaki emir, journal'da karsiligi olmasa da engel olmali."""
    broker = FakeBroker()
    broker.open_orders.append(
        OrderRef(
            broker_order_id="disaridan",
            client_order_id="elle-girilmis",
            symbol="SPY",
            submitted_at=NOW,
            status="new",
        )
    )
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    result = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert result.submitted == 0
    assert broker.submitted == []


def test_kill_switch_survives_a_process_restart(config: Config, conn: sqlite3.Connection) -> None:
    """Bellekteki bayrak sureci asmaz; karar veritabaninda durmali.

    systemd yeniden baslattiginda sistem gunu kapatmis oldugunu
    unutursa, kill-switch tetiklenen gunde tekrar islem acar.
    """
    broker = FakeBroker(account=make_account(equity=97_000, last_equity=100_000))
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})

    first = build_runner(config=config, conn=conn, broker=broker, market=market)
    assert first.run_once().halted

    # Surec yeniden basladi ve hesap da toparlandi.
    broker.account = make_account(equity=99_900, last_equity=100_000)
    second = build_runner(config=config, conn=conn, broker=broker, market=market)
    result = second.run_once()

    assert result.halted
    assert broker.submitted == []
    assert "gun kapali" in " ".join(result.notes)


def test_halt_lifts_on_the_next_trading_day(config: Config, conn: sqlite3.Connection) -> None:
    """Kill-switch gunluk; ertesi gun sistem normale donmeli."""
    broker = FakeBroker(account=make_account(equity=97_000, last_equity=100_000))
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    next_day = NOW + timedelta(days=1)
    broker.account = make_account()
    broker.positions = []
    tomorrow = build_runner(
        config=config,
        conn=conn,
        broker=broker,
        market=market,
        now=next_day,
    )
    market.bars_by_symbol = {"SPY": breakout_bars_at(next_day - timedelta(minutes=30))}
    assert not tomorrow.run_once().halted


def test_order_is_journaled_before_it_is_sent(config: Config, conn: sqlite3.Connection) -> None:
    """Once kaydet, sonra gonder.

    Ters sirada calisip da ikisinin arasinda surec olursa, brokerdaki
    emir journal'da hic gorunmez: dolmasindan dogan pozisyon hicbir
    karara atfedilemez ve mutabakat onu hesaba katamaz.
    """
    broker = FakeBroker(fail_submit=True)
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    row = conn.execute("SELECT * FROM orders").fetchone()
    assert row is not None, "gonderim basarisiz olsa da emir kayitli olmali"
    assert row["status"] == "submitting"
    assert row["broker_order_id"] is None


def test_unconfirmed_order_blocks_then_is_released(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Kesinlesmemis emir sembolu tikar, ama sonsuza kadar degil.

    Emir brokera ulasmis da olabilir; hemen yenisini gondermek
    pozisyonu ikiye katlar. Ama kayit sonsuza kadar duruyorsa sembol
    bir daha hic islem gormez. Ikisinin arasi: kisa bir bekleme.
    """
    broker = FakeBroker(fail_submit=True)
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)
    runner.run_once()

    broker.fail_submit = False
    # Bekleme suresi dolmadan yeni emir yok.
    runner.run_once()
    assert broker.submitted == []

    # Sure dolunca emir kayip sayilir ve sembolun onu acilir.
    later_now = NOW + timedelta(minutes=10)
    market.bars_by_symbol = {"SPY": breakout_bars_at(later_now - timedelta(minutes=30))}
    build_runner(config=config, conn=conn, broker=broker, market=market, now=later_now).run_once()

    assert conn.execute("SELECT status FROM orders WHERE status = 'lost'").fetchone() is not None


def test_blind_to_open_orders_means_no_new_entries(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Bekleyen emirleri goremeyen dongu giris yapmamali.

    Bos liste ile 'bilinmiyor' ayni sey degil: ikincisinde emir
    gonderirsek, dolmayi bekleyen bir emrin uzerine ikincisini
    gondermis olabiliriz.
    """
    broker = FakeBroker(fail_open_orders=True)
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    result = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert broker.submitted == []
    assert "bekleyen emirler bilinmiyor" in " ".join(result.notes)


def test_stale_entry_order_is_cancelled(config: Config, conn: sqlite3.Connection) -> None:
    """Kirilim sinyali zamana bagli: bayat emir iptal edilmeli."""
    broker = FakeBroker(submitted_at=NOW - timedelta(minutes=30))
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)
    runner.run_once()
    assert len(broker.open_orders) == 1

    result = runner.run_once()
    assert result.cancelled == 1
    assert broker.open_orders == []
    assert (
        conn.execute("SELECT status FROM orders WHERE status = 'canceled'").fetchone() is not None
    )


def test_protective_legs_are_never_cancelled_as_stale(
    config: Config, conn: sqlite3.Connection
) -> None:
    """Acik pozisyonu olan sembolde emir iptali yapilmaz.

    Koruma bacaklari 'bayat emir' degildir; iptal edilirlerse
    pozisyon korumasiz kalir - gozetimsiz bir sistemde en tehlikeli
    durum.
    """
    broker = FakeBroker(submitted_at=NOW - timedelta(hours=2))
    broker.positions = [
        Position(symbol="SPY", side=Side.BUY, qty=10, avg_entry_price=100.0, current_price=101.0)
    ]
    broker.open_orders.append(
        OrderRef(
            broker_order_id="koruma-bacagi",
            client_order_id="alpaca-leg",
            symbol="SPY",
            submitted_at=NOW - timedelta(hours=2),
            status="new",
        )
    )
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    result = build_runner(config=config, conn=conn, broker=broker, market=market).run_once()

    assert result.cancelled == 0
    assert len(broker.open_orders) == 1


def test_fills_are_written_to_the_audit_trail(config: Config, conn: sqlite3.Connection) -> None:
    broker = FakeBroker()
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    runner = build_runner(config=config, conn=conn, broker=broker, market=market)
    runner.run_once()
    broker.fill_order(broker.open_orders[0], price=100.8, at=NOW)
    runner.run_once()

    row = conn.execute("SELECT * FROM fills").fetchone()
    assert row is not None
    assert row["symbol"] == "SPY"
    assert row["price"] == pytest.approx(100.8)
