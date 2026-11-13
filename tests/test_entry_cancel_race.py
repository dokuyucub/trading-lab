"""Bayat giris iptali ile dolum arasindaki yaris (Codex #63/6777889127, 6840456161).

Runner pozisyonlari okur (SPY yok), bekleyen girisi gorur ve iptal
ister. Iptal asenkron kesinlesir; giris bu arada, hatta sonraki
okumalarin ARASINDA dolabilir. Iki sira sinaniyor:

  * Dolum iptal cagrisinin icinde, iptalden once olur.
  * Iptal kabul edilir ama `pending_cancel`da kalir; dolum sonraki
    turda pozisyon okunduktan SONRA, acik emirler okunurken olur.
    Acik listeden kaybolmak iptal sayilsaydi bu dolum "canceled"
    yazilir ve koruma kontrolunden kacardi.

Beklenen davranis:
  * iptal yalnizca girisin kendi kimligine gider; bacak kimligi hicbir
    senaryoda iptal cagrisina girmez;
  * sonuc girisin KENDI terminal durumundan (`get_order`) cikar; terminal
    olmayan iptal izlenir (journal'da `cancel_pending`) ve o sirada yeni
    giris engellenir;
  * dolum varsa stop bacaklari `max(dolan miktar, pozisyon)` miktarini
    kapsamali; kapsamiyorsa ya da durum okunamiyorsa gun kill-switch ile
    kapanir (fail-closed).

Iki yol da ayni kodu kullanir: normal gunde sure dolumu (TTL) ve gun
durumu okunamazken yasina bakmadan iptal (`entries_blocked`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import make_account
from test_runner import NOW, FakeBroker, FakeMarket, breakout_bars, build_runner
from tlab.config import Config, load_config
from tlab.core.types import BracketOrder, OrderRef, Position, Side
from tlab.engine.runner import SessionRunner
from tlab.errors import BrokerError
from tlab.journal.db import apply_migrations, connect
from tlab.journal.queries import halt_reason

PATHS = ["ttl", "blocked"]

Hook = Callable[["RacingBroker"], None]


@dataclass
class RacingBroker(FakeBroker):
    """Broker durumunu tam istenen anda degistiren sahte broker.

    `on_cancel`: iptal cagrisinin icinde, iptalden once calisir.
    `hold_cancel`: iptal kabul edilir ama emir `pending_cancel`da kalir.
    `on_list`: bir sonraki `list_open_orders` cagrisinin basinda calisir.
    """

    on_cancel: Hook | None = None
    hold_cancel: bool = False
    on_list: Hook | None = None

    def cancel_order(self, broker_order_id: str) -> None:
        if self.on_cancel is not None:
            hook, self.on_cancel = self.on_cancel, None
            hook(self)
        if not self.hold_cancel:
            super().cancel_order(broker_order_id)
            return
        self.cancelled_ids.append(broker_order_id)
        if all(o.broker_order_id != broker_order_id for o in self.open_orders):
            msg = f"emir iptal edilemez: {broker_order_id}"
            raise BrokerError(msg)
        self.open_orders = [
            o.model_copy(update={"status": "pending_cancel"})
            if o.broker_order_id == broker_order_id
            else o
            for o in self.open_orders
        ]

    def list_open_orders(self) -> list[OrderRef]:
        if self.on_list is not None:
            hook, self.on_list = self.on_list, None
            hook(self)
        return super().list_open_orders()


@dataclass
class Setup:
    broker: RacingBroker
    conn: sqlite3.Connection
    runner: SessionRunner
    entry: OrderRef
    order: BracketOrder
    config: Config
    market: FakeMarket

    def restart(self) -> SessionRunner:
        """Ayni journal ile yeni surec: bellekteki izleme kaybolur."""
        self.runner = build_runner(
            config=self.config, conn=self.conn, broker=self.broker, market=self.market
        )
        return self.runner


@pytest.fixture
def config(project_root: Path) -> Config:
    (project_root / "config" / "universe.yaml").write_text("symbols:\n  - SPY\n", encoding="utf-8")
    return load_config(project_root)


def prepare(path: str, config: Config, tmp_path: Path) -> Setup:
    """Ilk tur SPY girisini gonderir; ikinci tur onu iptal etmeye calisacak."""
    stale = path == "ttl"
    broker = RacingBroker(
        account=make_account(),
        submitted_at=NOW - timedelta(minutes=30) if stale else NOW,
    )
    market = FakeMarket(bars_by_symbol={"SPY": breakout_bars()})
    conn = connect(tmp_path / "journal.db")
    apply_migrations(conn)
    first = build_runner(config=config, conn=conn, broker=broker, market=market)
    assert first.run_once().submitted == 1
    [entry] = broker.open_orders
    [order] = broker.submitted
    assert order.qty >= 2
    setup = Setup(broker, conn, first, entry, order, config, market)
    if not stale:
        conn.execute("DROP TABLE daily_state")
        setup.restart()
    return setup


def legs(order: BracketOrder, *, stop_qty: float) -> list[OrderRef]:
    """Dolumla birlikte gorunur hale gelen bracket bacaklari."""
    return [
        OrderRef(
            broker_order_id="leg-stop",
            client_order_id="alpaca-leg-stop",
            symbol=order.symbol,
            submitted_at=NOW,
            status="new",
            side=Side.SELL,
            remaining_qty=stop_qty,
            stop_price=order.stop_loss,
        ),
        OrderRef(
            broker_order_id="leg-target",
            client_order_id="alpaca-leg-target",
            symbol=order.symbol,
            submitted_at=NOW,
            status="new",
            side=Side.SELL,
            remaining_qty=order.qty,
            limit_price=order.take_profit,
        ),
    ]


def hold_position(broker: FakeBroker, order: BracketOrder, qty: float) -> None:
    price = order.limit_price or 100.0
    broker.positions = [
        Position(
            symbol=order.symbol, side=Side.BUY, qty=qty, avg_entry_price=price, current_price=price
        )
    ]


def settle(broker: FakeBroker, entry: OrderRef, status: str, filled: float) -> None:
    """Giris acik listeden cikar ve terminal duruma gecer."""
    broker.open_orders = [
        o for o in broker.open_orders if o.broker_order_id != entry.broker_order_id
    ]
    broker.terminal[entry.broker_order_id] = entry.model_copy(
        update={"status": status, "filled_qty": filled, "side": Side.BUY}
    )


def status_of(conn: sqlite3.Connection, entry: OrderRef) -> str:
    row = conn.execute(
        "SELECT status FROM orders WHERE client_order_id = ?", (entry.client_order_id,)
    ).fetchone()
    return str(row[0])


def leg_ids(broker: FakeBroker) -> list[str]:
    return sorted(
        o.broker_order_id for o in broker.open_orders if o.broker_order_id.startswith("leg-")
    )


def assert_only_the_entry_was_cancelled(s: Setup) -> None:
    assert set(s.broker.cancelled_ids) == {s.entry.broker_order_id}
    assert s.broker.cancelled in ([], [None])


# --------------------------------------------------------------------------
# Dolum iptal cagrisinin icinde
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", PATHS)
def test_a_partial_fill_during_cancel_keeps_the_legs(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    filled = s.order.qty // 2

    def partial(broker: RacingBroker) -> None:
        broker.open_orders = [
            o.model_copy(update={"filled_qty": float(filled), "side": Side.BUY})
            if o.broker_order_id == s.entry.broker_order_id
            else o
            for o in broker.open_orders
        ]
        hold_position(broker, s.order, filled)
        broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty))

    s.broker.on_cancel = partial
    result = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert s.broker.cancelled == []
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert s.broker.closed == []
    assert not result.halted
    assert result.cancelled == 0
    assert status_of(s.conn, s.entry) == "filled"
    assert any("iptal sirasinda doldu" in note for note in result.notes)
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_a_full_fill_refuses_the_cancel_and_keeps_the_legs(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)

    def full(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", s.order.qty)
        hold_position(broker, s.order, s.order.qty)
        broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty))

    s.broker.on_cancel = full
    result = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert s.broker.cancelled == []
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert s.broker.closed == []
    assert not result.halted
    assert status_of(s.conn, s.entry) == "filled"
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("cover", ["none", "short"])
def test_an_unprotected_fill_during_cancel_halts_the_day(
    path: str, cover: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)

    def unprotected(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", s.order.qty)
        hold_position(broker, s.order, s.order.qty)
        if cover == "short":
            broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty - 1))

    s.broker.on_cancel = unprotected
    result = s.runner.run_once()

    assert_only_the_entry_was_cancelled(s)
    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    # Kapatma once butun emirleri iptal eder, sonra pozisyonu kapatir.
    assert s.broker.cancelled == [None]
    assert s.broker.closed == ["SPY"]
    assert result.evaluated == 0
    if path == "ttl":
        assert halt_reason(s.conn, result.now.date()) is not None
    assert s.runner.run_once().halted
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_broker_after_a_fill_halts_and_retries_the_flatten(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)

    def blind(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", s.order.qty)
        hold_position(broker, s.order, s.order.qty)
        broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty))
        broker.fail_open_orders = True

    s.broker.on_cancel = blind
    result = s.runner.run_once()

    assert result.halted
    assert s.broker.closed == []
    s.broker.fail_open_orders = False
    assert s.runner.run_once().halted
    assert s.broker.closed == ["SPY"]
    assert len(s.broker.submitted) == 1


# --------------------------------------------------------------------------
# Iptal kabul edildi ama kesinlesmedi; dolum sonraki okumalarin arasinda
# --------------------------------------------------------------------------


def accept_without_settling(s: Setup) -> None:
    """Ikinci tur: iptal kabul edilir, giris `pending_cancel`da kalir."""
    s.broker.hold_cancel = True
    result = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert result.entries_blocked
    assert any("iptali kesinlesmedi" in note for note in result.notes)
    assert result.cancelled == 0
    assert not result.halted
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert len(s.broker.submitted) == 1


def fill_while_listing(s: Setup, *, filled: float, stop_qty: float | None, visible: bool) -> None:
    """Sonraki tur: pozisyon okumasi bos; dolum acik emirler okunurken olur."""

    def late_fill(broker: RacingBroker) -> None:
        status = "filled" if filled >= s.order.qty else "canceled"
        settle(broker, s.entry, status, filled)
        if visible:
            hold_position(broker, s.order, filled)
        if stop_qty is not None:
            broker.open_orders.extend(legs(s.order, stop_qty=stop_qty))

    s.broker.on_list = late_fill


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("partial", [False, True])
def test_a_late_fill_with_full_legs_is_not_written_as_canceled(
    path: str, partial: bool, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    filled = float(s.order.qty // 2 if partial else s.order.qty)
    fill_while_listing(s, filled=filled, stop_qty=s.order.qty, visible=True)

    result = s.runner.run_once()

    assert status_of(s.conn, s.entry) == "filled"
    assert result.cancelled == 0
    assert not result.halted
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert s.broker.closed == []
    assert set(s.broker.cancelled_ids) == {s.entry.broker_order_id}
    assert any("iptal sirasinda doldu" in note for note in result.notes)
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("cover", ["none", "short"])
def test_a_late_unprotected_fill_halts_the_day(
    path: str, cover: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    fill_while_listing(
        s,
        filled=float(s.order.qty),
        stop_qty=None if cover == "none" else s.order.qty - 1,
        visible=True,
    )

    result = s.runner.run_once()

    assert status_of(s.conn, s.entry) != "canceled"
    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert s.broker.closed == ["SPY"]
    assert result.evaluated == 0
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("stop_qty", [None, "full"])
def test_a_fill_the_position_read_does_not_show_yet_is_still_checked(
    path: str, stop_qty: str | None, config: Config, tmp_path: Path
) -> None:
    """Gereken miktar emrin kendi dolumundan gelir; pozisyon gecikse de."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    fill_while_listing(
        s,
        filled=float(s.order.qty),
        stop_qty=None if stop_qty is None else s.order.qty,
        visible=False,
    )

    result = s.runner.run_once()

    # Korumasiz dolumda durum degismez; gun karari kalicidir.
    expected = "cancel_pending" if stop_qty is None else "filled"
    assert status_of(s.conn, s.entry) == expected
    assert result.halted is (stop_qty is None)
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_a_pending_cancel_that_settles_unfilled_is_written_as_canceled(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    fill_while_listing(s, filled=0.0, stop_qty=None, visible=False)

    result = s.runner.run_once()

    assert status_of(s.conn, s.entry) == "canceled"
    assert result.cancelled == 1
    assert not result.halted
    assert not any("kesinlesmedi" in note for note in result.notes)
    # Ikinci iptal gonderilmedi.
    assert s.broker.cancelled_ids == [s.entry.broker_order_id]


@pytest.mark.parametrize("path", PATHS)
def test_a_pending_cancel_stays_tracked_and_blocks_entries(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)

    again = s.runner.run_once()

    assert again.entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_a_restarted_process_takes_over_the_pending_cancel(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Izleme journal'da: yeni surec pozisyonlu sembolde de cozer."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    settle(s.broker, s.entry, "filled", float(s.order.qty))
    hold_position(s.broker, s.order, s.order.qty)

    result = s.restart().run_once()

    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert result.halted
    assert "koruma dogrulanamadi" in " ".join(result.notes)


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_entry_stays_tracked_and_blocks_entries(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)

    def vanish(broker: RacingBroker) -> None:
        broker.open_orders = []
        broker.fail_get_order = True

    s.broker.on_cancel = vanish
    result = s.runner.run_once()

    assert result.entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert result.cancelled == 0
    assert not result.halted
    assert len(s.broker.submitted) == 1


# --------------------------------------------------------------------------
# Dolum yok
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", PATHS)
def test_an_entry_that_expired_elsewhere_is_written_as_canceled(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Iptal reddedildi ama giris terminal durumda ve hic dolmamis."""
    s = prepare(path, config, tmp_path)
    s.broker.on_cancel = lambda broker: settle(broker, s.entry, "expired", 0.0)

    result = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert result.cancelled == 1
    assert not result.halted
    assert s.broker.closed == []
    assert status_of(s.conn, s.entry) == "canceled"


@pytest.mark.parametrize("path", PATHS)
def test_a_clean_cancel_is_written_as_canceled(path: str, config: Config, tmp_path: Path) -> None:
    s = prepare(path, config, tmp_path)

    result = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert s.broker.cancelled == []
    assert s.broker.open_orders == []
    assert result.cancelled == 1
    assert not result.halted
    assert status_of(s.conn, s.entry) == "canceled"


# --------------------------------------------------------------------------
# Iptal kesinlesmeden kismi dolum (Codex #63/6844629736)
# --------------------------------------------------------------------------


def partial_without_settling(
    s: Setup, *, status: str, filled: float, stop_qty: float | None
) -> None:
    """Giris acik kalir (terminal degil) ama bir kismi dolmustur."""
    s.broker.open_orders = [
        o.model_copy(update={"status": status, "filled_qty": filled, "side": Side.BUY})
        if o.broker_order_id == s.entry.broker_order_id
        else o
        for o in s.broker.open_orders
        if not o.broker_order_id.startswith("leg-")
    ]
    hold_position(s.broker, s.order, filled)
    if stop_qty is not None:
        s.broker.open_orders.extend(legs(s.order, stop_qty=stop_qty))


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("status", ["pending_cancel", "partially_filled"])
@pytest.mark.parametrize("cover", ["none", "short"])
def test_an_unsettled_partial_fill_without_cover_halts_the_day(
    path: str, status: str, cover: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    filled = 5.0
    partial_without_settling(
        s, status=status, filled=filled, stop_qty=None if cover == "none" else filled - 1
    )

    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert s.broker.closed == ["SPY"]
    assert result.evaluated == 0
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("status", ["pending_cancel", "partially_filled"])
def test_an_unsettled_partial_fill_with_cover_stays_tracked(
    path: str, status: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    partial_without_settling(s, status=status, filled=5.0, stop_qty=5.0)

    result = s.runner.run_once()

    assert not result.halted
    assert result.entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert s.broker.closed == []
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_a_growing_unsettled_fill_is_checked_again(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Kapsam ilk turdaki miktarla sabitlenmez."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    partial_without_settling(s, status="partially_filled", filled=3.0, stop_qty=3.0)
    assert not s.runner.run_once().halted

    partial_without_settling(s, status="partially_filled", filled=5.0, stop_qty=3.0)
    result = s.runner.run_once()

    assert result.halted
    assert s.broker.closed == ["SPY"]
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_a_restarted_process_checks_an_unsettled_partial_fill(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    partial_without_settling(s, status="partially_filled", filled=5.0, stop_qty=None)

    result = s.restart().run_once()

    assert result.halted
    assert "koruma dogrulanamadi" in " ".join(result.notes)
