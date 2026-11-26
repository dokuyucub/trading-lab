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
from test_runner import NOW, FakeBroker, FakeClock, FakeMarket, breakout_bars, build_runner
from tlab.config import Config, load_config
from tlab.core.types import BracketOrder, Fill, OrderRef, Position, Side
from tlab.engine.runner import MAX_CANCEL_ATTEMPTS, SessionRunner
from tlab.errors import BrokerError, JournalError
from tlab.journal.db import apply_migrations, connect
from tlab.journal.queries import halt_reason

PATHS = ["ttl", "blocked"]


class Crash(BaseException):
    """Surecin kesilmesi: `run_once` disina tasinir, hicbir yol yakalamaz."""


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
    crash_after_cancel: bool = False
    """Broker iptali kabul eder, surec sonucu yazamadan kesilir."""
    unreachable_cancels: int = 0
    """Bu kadar iptal istegi brokera hic ulasmaz (baglanti hatasi)."""
    lose_cancel_reply: bool = False
    """Broker iptali alir ama cevap kaybolur: cagiran hata gorur."""
    fail_positions: bool = False
    """Pozisyon okumasi hata verir."""
    fail_close: bool = False
    """Kapatma emri brokera ulasmaz; pozisyon acik kalir."""

    def close_position(self, symbol: str) -> OrderRef | None:
        if self.fail_close:
            msg = "pozisyon kapatilamadi"
            raise BrokerError(msg)
        return super().close_position(symbol)

    def get_positions(self) -> list[Position]:
        if self.fail_positions:
            msg = "pozisyonlar okunamadi"
            raise BrokerError(msg)
        return super().get_positions()

    def cancel_order(self, broker_order_id: str) -> None:
        if self.on_cancel is not None:
            hook, self.on_cancel = self.on_cancel, None
            hook(self)
        if self.unreachable_cancels > 0:
            self.unreachable_cancels -= 1
            self.cancelled_ids.append(broker_order_id)
            msg = "baglanti kurulamadi"
            raise BrokerError(msg)
        self._cancel(broker_order_id)
        if self.crash_after_cancel:
            raise Crash
        if self.lose_cancel_reply:
            msg = "cevap alinamadi"
            raise BrokerError(msg)

    def _cancel(self, broker_order_id: str) -> None:
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
    # Iptal reddedildi ve emir okunamadi: ulastigi dogrulanmadi.
    assert status_of(s.conn, s.entry) == "cancel_requested"
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
def test_an_unsettled_fill_the_position_read_does_not_show_yet_is_still_checked(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Giris kesinlesmedi ama 5 adet doldu; pozisyon okumasi henuz gostermiyor, stop yok.

    Gereken miktar girisin kendi dolumundan gelir: pozisyonun gorunmemesi
    korumasiz dolumu gizlemez.
    """
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    s.broker.open_orders = [
        o.model_copy(update={"status": "partially_filled", "filled_qty": 5.0, "side": Side.BUY})
        for o in s.broker.open_orders
    ]

    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)


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


# --------------------------------------------------------------------------
# Iptal niyeti write-ahead (Codex #63/6863854867)
# --------------------------------------------------------------------------


def crash_during_cancel(s: Setup, point: str) -> None:
    """Ikinci tur iptal sirasinda kesilir; journal'da yalnizca niyet kalir."""
    if point == "before_broker":

        def boom(_broker: RacingBroker) -> None:
            raise Crash

        s.broker.on_cancel = boom
    else:
        s.broker.hold_cancel = True
        s.broker.crash_after_cancel = True
    with pytest.raises(Crash):
        s.runner.run_once()
    s.broker.crash_after_cancel = False
    assert status_of(s.conn, s.entry) == "cancel_requested"
    sent = [] if point == "before_broker" else [s.entry.broker_order_id]
    assert s.broker.cancelled_ids == sent


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("point", ["before_broker", "after_broker"])
def test_a_crash_around_the_cancel_still_checks_an_unprotected_fill(
    path: str, point: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    crash_during_cancel(s, point)
    status = "partially_filled" if point == "before_broker" else "pending_cancel"
    partial_without_settling(s, status=status, filled=5.0, stop_qty=4.0)

    result = s.restart().run_once()

    # Iptal yeniden gonderildi; yalnizca girisin kimligine.
    assert set(s.broker.cancelled_ids) == {s.entry.broker_order_id}
    # Ulasmamis istek yeniden gonderildi; ulasmis olana (pending_cancel)
    # ikinci istek gitmedi.
    assert len(s.broker.cancelled_ids) == 1
    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert s.broker.closed == ["SPY"]
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("point", ["before_broker", "after_broker"])
def test_a_crash_around_the_cancel_keeps_a_covered_fill_tracked(
    path: str, point: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    crash_during_cancel(s, point)
    status = "partially_filled" if point == "before_broker" else "pending_cancel"
    partial_without_settling(s, status=status, filled=5.0, stop_qty=5.0)
    s.broker.hold_cancel = True

    result = s.restart().run_once()

    assert not result.halted
    assert result.entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert s.broker.closed == []
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert len(s.broker.submitted) == 1

    # Sonraki turda iptal artik `cancel_pending`: ikinci kez gonderilmez.
    sent = len(s.broker.cancelled_ids)
    assert s.runner.run_once().entries_blocked
    assert len(s.broker.cancelled_ids) == sent


@pytest.mark.parametrize("path", PATHS)
def test_an_unwritable_cancel_intent_sends_no_cancel(
    path: str, config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = prepare(path, config, tmp_path)
    write = s.runner.writer.update_order_status

    def refuse_intent(
        client_order_id: str, status: str, broker_order_id: str | None = None
    ) -> None:
        if status == "cancel_requested":
            msg = "journal yazilamadi"
            raise JournalError(msg)
        write(client_order_id, status, broker_order_id)

    monkeypatch.setattr(s.runner.writer, "update_order_status", refuse_intent)
    result = s.runner.run_once()

    assert s.broker.cancelled_ids == []
    assert result.entries_blocked
    assert any("iptal niyeti yazilamadi" in note for note in result.notes)
    assert not result.halted
    assert [o.broker_order_id for o in s.broker.open_orders] == [s.entry.broker_order_id]
    assert len(s.broker.submitted) == 1


# --------------------------------------------------------------------------
# Iletilemeyen iptal (Codex #63/6993997992 P1)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("restart", [False, True])
def test_an_unreached_cancel_is_sent_again(
    path: str, restart: bool, config: Config, tmp_path: Path
) -> None:
    """Istek brokera ulasmadi; emir hala aktif. Sonraki tur yeniden gonderir."""
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1

    first = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert [o.broker_order_id for o in s.broker.open_orders] == [s.entry.broker_order_id]
    # Ulasmadigi bilinmeyen istek "kabul edildi" sayilmaz.
    assert status_of(s.conn, s.entry) == "cancel_requested"
    assert first.entries_blocked

    runner = s.restart() if restart else s.runner
    second = runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id] * 2
    assert s.broker.open_orders == []
    assert status_of(s.conn, s.entry) == "canceled"
    assert second.cancelled == 1
    assert not second.halted


@pytest.mark.parametrize("path", PATHS)
def test_a_cancel_whose_reply_was_lost_is_not_sent_again(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Broker iptali aldi (pending_cancel) ama cevap kayboldu."""
    s = prepare(path, config, tmp_path)
    s.broker.hold_cancel = True
    s.broker.lose_cancel_reply = True

    first = s.runner.run_once()

    assert first.entries_blocked
    # Cevap kayboldu ama ayni turda emir `pending_cancel` okundu: istegin
    # ulastigi kanitlandi, satir cozumsuz istek olarak kalmaz.
    assert status_of(s.conn, s.entry) == "cancel_pending"
    s.broker.lose_cancel_reply = False

    second = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert second.entries_blocked
    assert not second.halted


@pytest.mark.parametrize("path", PATHS)
def test_a_cancel_that_never_reaches_the_broker_halts_the_day(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 99

    results = [s.runner.run_once() for _ in range(3)]

    assert [r.halted for r in results] == [False, False, False]
    assert all(r.entries_blocked for r in results)
    assert len(s.broker.cancelled_ids) == 3

    final = s.runner.run_once()

    assert final.halted
    assert "KILL-SWITCH: iptal iletilemedi: SPY" in " ".join(final.notes)
    # Kurtarma: butun emirler iptal edilir.
    assert s.broker.cancelled == [None]
    assert len(s.broker.cancelled_ids) == 3
    assert len(s.broker.submitted) == 1


# --------------------------------------------------------------------------
# Onceki seanstan kalan iz (Codex #63/6993997992 P2)
# --------------------------------------------------------------------------

LATER = NOW + timedelta(days=3)


def halt_on_an_unprotected_fill(s: Setup) -> None:
    """Ilk gun: dolum stopsuz, gun kapanir, pozisyon kapatilir; iz kalir."""

    def unprotected(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", s.order.qty)
        hold_position(broker, s.order, s.order.qty)

    s.broker.on_cancel = unprotected
    assert s.runner.run_once().halted
    assert s.broker.positions == []
    # Broker iptali reddetti (giris coktan doldu) ama giris terminal okundu:
    # istegin akibeti belli, satir cozumsuz istek olarak kalmaz.
    assert status_of(s.conn, s.entry) == "cancel_pending"


def next_session(s: Setup) -> SessionRunner:
    """Ayni journal, uc gun sonraki acik seans, yeni surec."""
    s.broker.clock = FakeClock(
        is_open=True,
        next_open=LATER - timedelta(minutes=30),
        next_close=LATER + timedelta(hours=6),
    )
    s.runner = build_runner(
        config=s.config, conn=s.conn, broker=s.broker, market=s.market, now=LATER
    )
    return s.runner


@pytest.mark.parametrize("path", PATHS)
def test_a_flat_account_in_a_later_session_is_not_locked_by_an_old_fill(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    halt_on_an_unprotected_fill(s)

    result = next_session(s).run_once()

    assert not result.halted
    assert status_of(s.conn, s.entry) == "filled"
    if path == "ttl":
        assert not result.entries_blocked
    # Iz kapandi: sonraki tur da kilitlenmez.
    assert not s.runner.run_once().halted


@pytest.mark.parametrize("path", PATHS)
def test_a_position_left_from_an_old_fill_is_still_protected(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    halt_on_an_unprotected_fill(s)
    hold_position(s.broker, s.order, 5.0)

    result = next_session(s).run_once()

    assert result.halted
    assert "koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert s.broker.closed[-1] == "SPY"


@pytest.mark.parametrize("path", PATHS)
def test_a_covered_position_left_from_an_old_fill_closes_the_tracking(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    halt_on_an_unprotected_fill(s)
    hold_position(s.broker, s.order, 5.0)
    s.broker.open_orders.extend(legs(s.order, stop_qty=5.0))

    result = next_session(s).run_once()

    assert not result.halted
    assert status_of(s.conn, s.entry) == "filled"
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]


# --------------------------------------------------------------------------
# Koruma kaniti ile gerceklesme ihtimali ayri sorular
# (Codex #63/7115896065, 7116120239)
# --------------------------------------------------------------------------

NOT_PROTECTIVE = [
    "pending_cancel",
    "pending_replace",
    "held",
    "accepted",
    "pending_new",
    "accepted_for_bidding",
    "beklenmeyen_durum",
]


def legs_with_stop_status(order: BracketOrder, stop_status: str) -> list[OrderRef]:
    stop, target = legs(order, stop_qty=order.qty)
    return [stop.model_copy(update={"status": stop_status}), target]


@pytest.mark.parametrize("stop_status", NOT_PROTECTIVE)
@pytest.mark.parametrize("path", PATHS)
def test_a_stop_without_protective_status_is_not_protection(
    path: str, stop_status: str, config: Config, tmp_path: Path
) -> None:
    """Iptali/degisimi suren, borsaya ulasmamis, `held` ya da bilinmeyen stop korumaz.

    Bekleme yok: gun ILK turda kapanir (Codex #63/7139373707, 7154998289).

    `held` bilincli olarak fail-closed: tam dolumdan sonra calistigi bu
    repoda dogrulanmadi (unattended-paper.md §4).
    """
    s = prepare(path, config, tmp_path)

    def fill(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", s.order.qty)
        hold_position(broker, s.order, s.order.qty)
        broker.open_orders.extend(legs_with_stop_status(s.order, stop_status))

    s.broker.on_cancel = fill
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert status_of(s.conn, s.entry) != "filled"
    assert s.broker.closed == ["SPY"]


@pytest.mark.parametrize("path", PATHS)
def test_a_held_stop_under_a_partially_filled_parent_is_not_protection(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Ebeveyn kismi dolumda: bacaklar henuz etkin degil (`held`)."""
    s = prepare(path, config, tmp_path)

    def partial(broker: RacingBroker) -> None:
        broker.open_orders = [
            o.model_copy(update={"status": "partially_filled", "filled_qty": 5.0})
            if o.broker_order_id == s.entry.broker_order_id
            else o
            for o in broker.open_orders
        ]
        hold_position(broker, s.order, 5.0)
        stop, target = legs(s.order, stop_qty=5.0)
        broker.open_orders.extend(
            [
                stop.model_copy(update={"status": "held"}),
                target.model_copy(update={"status": "held"}),
            ]
        )

    s.broker.hold_cancel = True
    s.broker.on_cancel = partial
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert s.broker.closed == ["SPY"]


@pytest.mark.parametrize("path", PATHS)
def test_a_new_stop_leg_is_protection(path: str, config: Config, tmp_path: Path) -> None:
    """Karsilastirma: ayni senaryoda `new` stop korur, gun kapanmaz."""
    s = prepare(path, config, tmp_path)

    def fill(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", s.order.qty)
        hold_position(broker, s.order, s.order.qty)
        broker.open_orders.extend(legs_with_stop_status(s.order, "new"))

    s.broker.on_cancel = fill
    result = s.runner.run_once()

    assert not result.halted
    assert status_of(s.conn, s.entry) == "filled"
    assert s.broker.closed == []


def session_after(s: Setup, days: int) -> SessionRunner:
    """`LATER`dan `days` gun sonraki acik seans, yeni surec."""
    now = LATER + timedelta(days=days)
    s.broker.clock = FakeClock(
        is_open=True,
        next_open=now - timedelta(minutes=30),
        next_close=now + timedelta(hours=6),
    )
    s.runner = build_runner(config=s.config, conn=s.conn, broker=s.broker, market=s.market, now=now)
    return s.runner


def halt_on_an_orphan_exit(s: Setup, stop_status: str) -> None:
    """Pozisyon sifir, onceki seanstan `stop_status` durumlu satis stopu kalmis."""
    halt_on_an_unprotected_fill(s)
    stop, _ = legs(s.order, stop_qty=s.order.qty)
    s.broker.open_orders.append(stop.model_copy(update={"status": stop_status}))

    result = next_session(s).run_once()

    assert result.halted
    assert "koruma dogrulanamadi: SPY" in " ".join(result.notes)
    # Guvenli kapatma butun emirleri iptal eder; kalan stop dusurulur.
    assert s.broker.cancelled[-1] is None
    assert leg_ids(s.broker) == []
    # Iz korunur: broker sonucu bildirene kadar her seans yeniden uzlastirilir.
    assert status_of(s.conn, s.entry) in ("cancel_requested", "cancel_pending")


@pytest.mark.parametrize("stop_status", ["new", *NOT_PROTECTIVE])
@pytest.mark.parametrize("path", PATHS)
def test_an_orphan_exit_that_was_cancelled_leaves_a_flat_account(
    path: str, stop_status: str, config: Config, tmp_path: Path
) -> None:
    """Kalan cikis emri (iptali surse de) gerceklesebilir; iptal kesinlesince duz."""
    s = prepare(path, config, tmp_path)
    halt_on_an_orphan_exit(s, stop_status)

    # Sonraki seans: iptal kesinlesti, pozisyon da emir de yok.
    after = session_after(s, 1).run_once()

    assert not after.halted
    assert status_of(s.conn, s.entry) == "filled"
    assert not s.runner.run_once().halted


@pytest.mark.parametrize("path", PATHS)
def test_an_orphan_exit_that_filled_is_closed_in_the_next_session(
    path: str, config: Config, tmp_path: Path
) -> None:
    """`pending_cancel` stop iptalden once doldu: ters pozisyon (SELL 5)."""
    s = prepare(path, config, tmp_path)
    halt_on_an_orphan_exit(s, "pending_cancel")
    price = s.order.limit_price or 100.0
    s.broker.positions = [
        Position(symbol="SPY", side=Side.SELL, qty=5.0, avg_entry_price=price, current_price=price)
    ]

    after = session_after(s, 1).run_once()

    assert after.halted
    assert "koruma dogrulanamadi: SPY" in " ".join(after.notes)
    assert s.broker.closed[-1] == "SPY"
    assert s.broker.positions == []
    assert status_of(s.conn, s.entry) != "filled"


# --------------------------------------------------------------------------
# Koruma icin bekleme yok; okuma hatasi ve yeniden baslatma sureyi uzatamaz
# (Codex #63/7139373707, 7154998289)
# --------------------------------------------------------------------------


def fill_with_stop_status(s: Setup, stop_status: str) -> None:
    """Iptal sirasinda giris tamamen dolar; tek satis stopu `stop_status`."""

    def fill(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", s.order.qty)
        hold_position(broker, s.order, s.order.qty)
        broker.open_orders.extend(legs_with_stop_status(s.order, stop_status))

    s.broker.on_cancel = fill


def test_a_halt_for_an_unprotected_fill_is_read_back_after_a_restart(
    config: Config, tmp_path: Path
) -> None:
    """Saglikli journal: karar `daily_state`e yazilir ve yeni baglantidan okunur."""
    s = prepare("ttl", config, tmp_path)
    fill_with_stop_status(s, "accepted")

    first = s.runner.run_once()

    assert first.halted
    assert s.broker.closed == ["SPY"]
    assert s.broker.positions == []

    # Baglanti kapanir; kalici kayit yeniden acilan baglantidan okunur.
    s.conn.close()
    s.conn = connect(tmp_path / "journal.db")
    reason = halt_reason(s.conn, first.now.date())
    assert reason is not None
    assert "koruma dogrulanamadi: SPY" in reason

    # Giris dolumu sonradan kapsanmis gorunse bile gun acilmaz: yeni surec
    # yeni bir karar vermez, kalici kaydi okur.
    s.broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty))
    again = s.restart().run_once()

    assert again.halted
    notes = " ".join(again.notes)
    assert f"gun kapali: {reason}" in notes
    assert "KILL-SWITCH:" not in notes
    assert len(s.broker.submitted) == 1


def test_an_unpersisted_halt_is_rebuilt_from_the_tracked_entry_after_a_restart(
    config: Config, tmp_path: Path
) -> None:
    """`daily_state` yazilamiyor: karar yalniz surec belleginde kalir.

    Yeni surec o bellegi goremez. Davranis yine ayni olmali: izlenen giris
    dolumu ve korumasiz pozisyonu yeniden gosterir, yeni giris acilmaz ve
    brokerda kalan pozisyon yeniden guvenli kapatmaya alinir.
    """
    s = prepare("blocked", config, tmp_path)
    fill_with_stop_status(s, "accepted")
    s.broker.fail_close = True

    first = s.runner.run_once()

    assert first.halted
    assert "kill-switch karari journal'a yazilamadi" in " ".join(first.notes)
    # Kapatma brokera ulasmadi: pozisyon acik, iz journal'da duruyor.
    assert s.broker.closed == []
    assert len(s.broker.positions) == 1
    assert status_of(s.conn, s.entry) in ("cancel_requested", "cancel_pending")

    s.conn.close()
    s.conn = connect(tmp_path / "journal.db")
    s.broker.fail_close = False
    again = s.restart().run_once()

    assert again.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(again.notes)
    assert s.broker.closed == ["SPY"]
    assert s.broker.positions == []
    assert len(s.broker.submitted) == 1


def mixed_stops(order: BracketOrder, *, new_qty: float, accepted_qty: float) -> list[OrderRef]:
    stop, target = legs(order, stop_qty=new_qty)
    extra = stop.model_copy(
        update={
            "broker_order_id": "leg-stop-2",
            "client_order_id": "alpaca-leg-stop-2",
            "status": "accepted",
            "remaining_qty": accepted_qty,
        }
    )
    return [stop, extra, target]


@pytest.mark.parametrize("path", PATHS)
def test_a_transitional_stop_does_not_complete_the_cover(
    path: str, config: Config, tmp_path: Path
) -> None:
    """`new` stop bir eksik; kalan miktari `accepted` stop tamamlayamaz."""
    s = prepare(path, config, tmp_path)
    qty = s.order.qty

    def short_cover(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", qty)
        hold_position(broker, s.order, qty)
        broker.open_orders.extend(mixed_stops(s.order, new_qty=qty - 1, accepted_qty=1))

    s.broker.on_cancel = short_cover
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert s.broker.closed == ["SPY"]
    assert status_of(s.conn, s.entry) != "filled"


@pytest.mark.parametrize("path", PATHS)
def test_a_transitional_extra_stop_does_not_delay_a_covered_fill(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    qty = s.order.qty

    def covered(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", qty)
        hold_position(broker, s.order, qty)
        broker.open_orders.extend(mixed_stops(s.order, new_qty=qty, accepted_qty=1))

    s.broker.on_cancel = covered
    result = s.runner.run_once()

    assert not result.halted
    assert status_of(s.conn, s.entry) == "filled"


def track_a_covered_partial_fill(s: Setup) -> None:
    """Ilk tur: kismi dolum stopla kapsaniyor, giris kesinlesmedi; iz suruyor."""
    accept_without_settling(s)
    partial_without_settling(s, status="partially_filled", filled=5.0, stop_qty=5.0)
    first = s.runner.run_once()
    assert not first.halted
    assert first.entries_blocked
    assert s.broker.closed == []


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_entry_does_not_hide_an_unprotected_position(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Stop duser ve giris okunamaz: pozisyon goruluyor, gun o turda kapanir."""
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)

    s.broker.open_orders = [o for o in s.broker.open_orders if o.broker_order_id != "leg-stop"]
    s.broker.fail_get_order = True
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert s.broker.closed == ["SPY"]
    assert status_of(s.conn, s.entry) != "filled"


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_entry_with_a_covered_position_stays_tracked(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)

    s.broker.fail_get_order = True
    for _ in range(3):
        result = s.runner.run_once()
        assert not result.halted
        assert result.entries_blocked
    assert s.broker.closed == []
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert status_of(s.conn, s.entry) == "cancel_pending"


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_entry_with_unreadable_orders_halts_when_a_position_shows(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Pozisyon goruluyor, stoplar okunamiyor: koruma kanitlanamaz."""
    s = prepare(path, config, tmp_path)

    def blind(broker: RacingBroker) -> None:
        hold_position(broker, s.order, 5.0)
        broker.open_orders.extend(legs(s.order, stop_qty=5.0))
        broker.fail_get_order = True
        broker.fail_open_orders = True

    s.broker.on_cancel = blind
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    # Emir listesi okunamadigi icin iptal teyit edilemedi: rakip kapatma yok.
    assert s.broker.closed == []
    assert len(s.broker.positions) == 1

    # Emir listesi geri geldi (giris hala okunamiyor): kapatma yeniden denenir.
    s.broker.fail_open_orders = False
    again = s.runner.run_once()

    assert again.halted
    assert s.broker.closed == ["SPY"]
    assert s.broker.positions == []
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_entry_with_unreadable_positions_stays_tracked(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Hicbir sey okunamiyor: bilgi yok; iz ve giris engeli surer, gun kapanmaz."""
    s = prepare(path, config, tmp_path)

    def blind(broker: RacingBroker) -> None:
        broker.fail_get_order = True
        broker.fail_positions = True

    s.broker.on_cancel = blind
    result = s.runner.run_once()

    assert not result.halted
    assert result.entries_blocked
    assert status_of(s.conn, s.entry) in ("cancel_requested", "cancel_pending")
    assert len(s.broker.submitted) == 1


# --------------------------------------------------------------------------
# Ofis incelemesi (docs/office/raporlar/S1-hata-avi-pr63-05df92d.md, B1-B4)
# --------------------------------------------------------------------------


def reported_fill(
    s: Setup, side: Side, qty: float, broker_id: str, client_id: str, kind: str, after: int
) -> Fill:
    """Brokerin bildirdigi gerceklesme (mutabakatin girdisi)."""
    return Fill(
        broker_order_id=broker_id,
        client_order_id=client_id,
        symbol="SPY",
        side=side,
        qty=qty,
        price=s.order.stop_loss,
        filled_at=NOW + timedelta(seconds=after),
        order_type=kind,
    )


def entry_fill(s: Setup, qty: float) -> Fill:
    return reported_fill(
        s, Side.BUY, qty, s.entry.broker_order_id, s.entry.client_order_id, "limit", 0
    )


def stop_fill(s: Setup, qty: float) -> Fill:
    return reported_fill(s, Side.SELL, qty, "leg-stop", "alpaca-leg-stop", "stop", 30)


def reopen(s: Setup, tmp_path: Path) -> SessionRunner:
    """Baglanti kapanir; ayni journal ile yeni surec."""
    s.conn.close()
    s.conn = connect(tmp_path / "journal.db")
    return s.restart()


@pytest.mark.parametrize("path", PATHS)
def test_reconciliation_does_not_overwrite_a_tracked_entry(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Mutabakat izlenen satiri `closed` yapmaz; yeni surec izi bulur (B1)."""
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)  # giris kismen doldu (5), pozisyon 5, stop `new` 5
    assert status_of(s.conn, s.entry) == "cancel_pending"

    # Stop tetiklenir (5 satilir); giris 3 adet daha dolar: pozisyon 3, stop yok.
    s.broker.fills = [entry_fill(s, 5.0), stop_fill(s, 5.0)]
    partial_without_settling(s, status="partially_filled", filled=8.0, stop_qty=None)
    hold_position(s.broker, s.order, 3.0)
    result = s.restart().run_once()

    assert result.halted
    assert "koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert s.broker.closed == ["SPY"]


def test_reconciliation_closes_an_untracked_entry(config: Config, tmp_path: Path) -> None:
    """Karsilastirma: izlemede olmayan giris islemi kapaninca `closed` olur."""
    s = prepare("ttl", config, tmp_path)
    qty = float(s.order.qty)
    settle(s.broker, s.entry, "filled", qty)
    s.broker.fills = [entry_fill(s, qty), stop_fill(s, qty)]

    result = s.runner.run_once()

    assert not result.halted
    assert status_of(s.conn, s.entry) == "closed"


def test_mark_order_closed_skips_only_the_listed_statuses(config: Config, tmp_path: Path) -> None:
    s = prepare("ttl", config, tmp_path)
    writer = s.runner.writer
    cid = s.entry.client_order_id
    tracked = ("cancel_requested", "cancel_pending")

    for status in tracked:
        writer.update_order_status(cid, status)
        writer.mark_order_closed(cid, unless=tracked)
        assert status_of(s.conn, s.entry) == status

    writer.update_order_status(cid, "filled")
    writer.mark_order_closed(cid, unless=tracked)
    assert status_of(s.conn, s.entry) == "closed"

    with pytest.raises(ValueError, match="bos olamaz"):
        writer.mark_order_closed(cid, unless=())


def test_an_unpersisted_halt_survives_a_reconciled_exit_fill(
    config: Config, tmp_path: Path
) -> None:
    """Gun yalniz bellekte kapali; stop kismen dolar; yeni surec yine kapatir (B1b)."""
    s = prepare("blocked", config, tmp_path)
    qty = float(s.order.qty)

    def short_cover(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", qty)
        hold_position(broker, s.order, qty)
        broker.open_orders.extend(legs(s.order, stop_qty=5.0))

    s.broker.on_cancel = short_cover
    s.broker.fail_close = True
    assert s.runner.run_once().halted

    # Stop, iptali kesinlesmeden tetiklendi ve 5 adet satti; kalan pozisyon stopsuz.
    s.broker.fills = [entry_fill(s, qty), stop_fill(s, 5.0)]
    hold_position(s.broker, s.order, qty - 5)
    s.broker.fail_close = False
    runner = reopen(s, tmp_path)
    halted = [runner.run_once().halted for _ in range(3)]

    assert all(halted)
    assert status_of(s.conn, s.entry) != "closed"
    assert s.broker.closed == ["SPY"]
    assert s.broker.positions == []


@pytest.mark.parametrize("path", PATHS)
def test_the_turn_start_position_is_used_when_the_reread_fails(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Giris ve ikinci pozisyon okumasi hata verir; tur basi goruntusu yeter (B2)."""
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)  # pozisyon 5, stop `new` 5
    s.broker.open_orders = [o for o in s.broker.open_orders if o.broker_order_id != "leg-stop"]
    s.broker.fail_get_order = True

    def fail_later_position_reads(broker: RacingBroker) -> None:
        broker.fail_positions = True

    # Tur basindaki okuma basarili; sonraki pozisyon okumalari hata verir.
    s.broker.on_list = fail_later_position_reads
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_entry_counts_toward_the_cancel_attempt_limit(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Ulasmayan iptal + okunamayan giris: sinir okuma hatasiyla uzamaz (B3)."""
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1
    assert s.runner.run_once().entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_requested"

    s.broker.fail_get_order = True
    results = [s.runner.run_once() for _ in range(MAX_CANCEL_ATTEMPTS)]

    assert [r.halted for r in results[:-1]] == [False] * (MAX_CANCEL_ATTEMPTS - 1)
    assert results[-1].halted
    assert "iptal iletilemedi: SPY" in " ".join(results[-1].notes)
    # Hesap genelindeki iptal bayat girisi de kapsar.
    assert s.broker.open_orders == []
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("filled", [0.0, None])
@pytest.mark.parametrize("path", PATHS)
def test_a_stale_fill_report_does_not_hide_a_visible_position(
    path: str, filled: float | None, config: Config, tmp_path: Path
) -> None:
    """Giris okunuyor, dolumu 0 ya da bilinmiyor; pozisyon goruluyor, stop yok (B4)."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    s.broker.open_orders = [
        o.model_copy(update={"status": "partially_filled", "filled_qty": filled, "side": Side.BUY})
        for o in s.broker.open_orders
    ]
    hold_position(s.broker, s.order, 5.0)

    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert s.broker.closed == ["SPY"]


@pytest.mark.parametrize("path", PATHS)
def test_a_canceled_entry_with_a_visible_position_keeps_the_tracking(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Giris `canceled`, dolum 0, ama pozisyon var ve stopsuz: iz kapanmaz (B4)."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    settle(s.broker, s.entry, "canceled", 0.0)
    hold_position(s.broker, s.order, 5.0)

    result = s.runner.run_once()

    assert result.halted
    assert status_of(s.conn, s.entry) != "canceled"
    assert s.broker.closed == ["SPY"]


@pytest.mark.parametrize("path", PATHS)
def test_a_canceled_entry_with_a_covered_position_is_written_as_canceled(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Karsilastirma: ayni durumda pozisyon stopla kapsaniyorsa gun kapanmaz."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    settle(s.broker, s.entry, "canceled", 0.0)
    hold_position(s.broker, s.order, 5.0)
    s.broker.open_orders.extend(legs(s.order, stop_qty=5.0))

    result = s.runner.run_once()

    assert not result.halted
    assert status_of(s.conn, s.entry) == "canceled"
    assert s.broker.closed == []


@pytest.mark.parametrize("stop", ["accepted", "held", "short"])
@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_entry_needs_a_protective_stop_for_the_whole_position(
    path: str, stop: str, config: Config, tmp_path: Path
) -> None:
    """Okunamayan giris dalinda da stopun durumu ve miktari sayilir."""
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)  # pozisyon 5, stop `new` 5
    update = {"remaining_qty": 4.0} if stop == "short" else {"status": stop}
    s.broker.open_orders = [
        o.model_copy(update=update) if o.broker_order_id == "leg-stop" else o
        for o in s.broker.open_orders
    ]
    s.broker.fail_get_order = True

    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)


@pytest.mark.parametrize("path", PATHS)
def test_a_position_that_appears_later_is_checked_while_the_entry_is_unreadable(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    s.broker.fail_get_order = True
    assert not s.runner.run_once().halted

    hold_position(s.broker, s.order, 4.0)
    result = s.runner.run_once()

    assert result.halted
    assert s.broker.closed == ["SPY"]


@pytest.mark.parametrize("unreadable", [False, True])
@pytest.mark.parametrize("cover", ["none", "wrong_side", "full"])
@pytest.mark.parametrize("path", PATHS)
def test_a_short_position_needs_a_buy_stop(
    path: str, cover: str, unreadable: bool, config: Config, tmp_path: Path
) -> None:
    """Satis yonlu giris: yalniz alis yonlu stop korur; giris okunsa da okunmasa da."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    price = s.order.limit_price or 100.0
    qty = float(s.order.qty)
    s.broker.terminal[s.entry.broker_order_id] = s.entry.model_copy(
        update={"status": "filled", "filled_qty": qty, "side": Side.SELL}
    )
    s.broker.positions = [
        Position(symbol="SPY", side=Side.SELL, qty=qty, avg_entry_price=price, current_price=price)
    ]
    sell_stop = legs(s.order, stop_qty=qty)[0]
    covers: dict[str, list[OrderRef]] = {
        "none": [],
        "wrong_side": [sell_stop],
        "full": [sell_stop.model_copy(update={"side": Side.BUY})],
    }
    s.broker.open_orders = covers[cover]
    s.broker.fail_get_order = unreadable

    assert s.runner.run_once().halted is (cover != "full")


# --------------------------------------------------------------------------
# Sembol yalitimi (Onay Kurulu, S1-onay-kurulu-pr63-8fd2234 N1)
# --------------------------------------------------------------------------


def other_symbol_stop(s: Setup, qty: float) -> OrderRef:
    """Baska bir sembolun (QQQ) satis stopu: SPY icin koruma degildir."""
    stop = legs(s.order, stop_qty=qty)[0]
    return stop.model_copy(
        update={
            "symbol": "QQQ",
            "broker_order_id": "other-stop",
            "client_order_id": "alpaca-other-stop",
        }
    )


@pytest.mark.parametrize("path", PATHS)
def test_another_symbols_stop_is_not_cover_for_a_read_fill(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    qty = float(s.order.qty)

    def fill(broker: RacingBroker) -> None:
        settle(broker, s.entry, "filled", qty)
        hold_position(broker, s.order, qty)
        broker.open_orders.append(other_symbol_stop(s, qty))

    s.broker.on_cancel = fill
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)


@pytest.mark.parametrize("path", PATHS)
def test_another_symbols_stop_is_not_cover_when_the_entry_is_unreadable(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    track_a_covered_partial_fill(s)  # SPY pozisyon 5, SPY stop `new` 5
    s.broker.open_orders = [o for o in s.broker.open_orders if o.broker_order_id != "leg-stop"]
    s.broker.open_orders.append(other_symbol_stop(s, 5.0))
    s.broker.fail_get_order = True

    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)


@pytest.mark.parametrize("path", PATHS)
def test_another_symbols_stop_is_not_cover_for_a_stale_fill_report(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    settle(s.broker, s.entry, "canceled", 0.0)
    hold_position(s.broker, s.order, 5.0)
    s.broker.open_orders.append(other_symbol_stop(s, 5.0))

    result = s.runner.run_once()

    assert result.halted
    assert status_of(s.conn, s.entry) != "canceled"


@pytest.mark.parametrize("path", PATHS)
def test_another_symbols_position_does_not_count_for_an_unreadable_entry(
    path: str, config: Config, tmp_path: Path
) -> None:
    """SPY girisi okunamiyor, SPY pozisyonu yok; QQQ kendi stopuyla korunuyor."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    price = s.order.limit_price or 100.0
    s.broker.positions = [
        Position(symbol="QQQ", side=Side.BUY, qty=5.0, avg_entry_price=price, current_price=price)
    ]
    s.broker.open_orders.append(other_symbol_stop(s, 5.0))
    s.broker.fail_get_order = True

    result = s.runner.run_once()

    assert not result.halted
    assert result.entries_blocked
    assert s.broker.closed == []


@pytest.mark.parametrize("path", PATHS)
def test_another_symbols_position_does_not_lock_an_old_fill(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Onceki seansin SPY girisi: SPY duz; QQQ pozisyonu SPY izini acik tutmaz."""
    s = prepare(path, config, tmp_path)
    halt_on_an_unprotected_fill(s)
    price = s.order.limit_price or 100.0
    s.broker.positions = [
        Position(symbol="QQQ", side=Side.BUY, qty=5.0, avg_entry_price=price, current_price=price)
    ]
    s.broker.open_orders.append(other_symbol_stop(s, 5.0))

    result = next_session(s).run_once()

    assert not result.halted
    assert status_of(s.conn, s.entry) == "filled"


# --------------------------------------------------------------------------
# Iz kapanmadan once guncel pozisyon; onceki seansin cikis emri; devralinan
# cozumsuz iptal (Codex #63/7168523270)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", PATHS)
def test_a_position_that_appears_after_the_first_read_keeps_the_tracking(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Tur basinda pozisyon yok; sonra giris `canceled`/0 ve pozisyon 5, stop yok."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)

    def late(broker: RacingBroker) -> None:
        settle(broker, s.entry, "canceled", 0.0)
        hold_position(broker, s.order, 5.0)

    s.broker.on_list = late
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert status_of(s.conn, s.entry) != "canceled"
    assert s.broker.closed == ["SPY"]


@pytest.mark.parametrize("path", PATHS)
def test_an_unknown_position_does_not_prove_a_flat_account(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Giris `canceled`/0; guncel pozisyon okunamiyor, tur basi goruntusu bos."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)

    def blind(broker: RacingBroker) -> None:
        settle(broker, s.entry, "canceled", 0.0)
        broker.fail_positions = True

    s.broker.on_list = blind
    result = s.runner.run_once()

    assert not result.halted
    assert result.entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_pending"

    # Okuma geri geldi ve hesap gercekten bos: iz kapanir.
    s.broker.fail_positions = False
    after = s.runner.run_once()

    assert not after.halted
    assert status_of(s.conn, s.entry) == "canceled"


@pytest.mark.parametrize("path", PATHS)
def test_a_failed_reread_falls_back_to_a_seen_position_for_a_zero_fill(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Giris `canceled`/0; tur basinda stopsuz pozisyon goruldu, yeniden okuma hata verir."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    settle(s.broker, s.entry, "canceled", 0.0)
    hold_position(s.broker, s.order, 5.0)

    def fail_later_position_reads(broker: RacingBroker) -> None:
        broker.fail_positions = True

    s.broker.on_list = fail_later_position_reads
    result = s.runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert status_of(s.conn, s.entry) != "canceled"


def halt_on_a_late_unprotected_fill(s: Setup) -> None:
    """Ilk gun: iptal brokerca dogrulanir (`cancel_pending`), sonra stopsuz dolum."""
    accept_without_settling(s)
    fill_while_listing(s, filled=float(s.order.qty), stop_qty=None, visible=True)
    assert s.runner.run_once().halted
    assert s.broker.positions == []
    assert status_of(s.conn, s.entry) == "cancel_pending"


def old_exit_order(s: Setup, status: str) -> OrderRef:
    """Sonraki seansa tasinan satis stopu."""
    return legs(s.order, stop_qty=s.order.qty)[0].model_copy(update={"status": status})


@pytest.mark.parametrize("stop_status", ["new", "held", "pending_cancel"])
@pytest.mark.parametrize("path", PATHS)
def test_an_old_exit_order_is_cancelled_even_when_the_entry_is_unreadable(
    path: str, stop_status: str, config: Config, tmp_path: Path
) -> None:
    """Onceki seans, iptal dogrulanmis, giris okunamiyor, pozisyon sifir.

    Kalan cikis emri gerceklesebilir: sonraki seansin ILK turunda gun
    kapanir, hesap genelindeki iptal emri kapsar, iz korunur.
    """
    s = prepare(path, config, tmp_path)
    halt_on_a_late_unprotected_fill(s)
    s.broker.open_orders.append(old_exit_order(s, stop_status))
    s.broker.fail_get_order = True

    result = next_session(s).run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert s.broker.cancelled[-1] is None
    assert leg_ids(s.broker) == []
    assert status_of(s.conn, s.entry) == "cancel_pending"


@pytest.mark.parametrize("path", PATHS)
def test_an_old_exit_order_is_cancelled_even_when_the_position_is_unknown(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Giris ve guncel pozisyon okunamiyor; gorunen eski cikis emri yine sahipsizdir."""
    s = prepare(path, config, tmp_path)
    halt_on_a_late_unprotected_fill(s)
    s.broker.open_orders.append(old_exit_order(s, "new"))
    runner = next_session(s)
    s.broker.fail_get_order = True

    def fail_later_position_reads(broker: RacingBroker) -> None:
        broker.fail_positions = True

    s.broker.on_list = fail_later_position_reads
    result = runner.run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert status_of(s.conn, s.entry) == "cancel_pending"


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_old_entry_on_an_empty_account_stays_tracked(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Karsilastirma: ayni durum, ama sembolde emir yok. Gun kapanmaz."""
    s = prepare(path, config, tmp_path)
    halt_on_a_late_unprotected_fill(s)
    s.broker.fail_get_order = True

    result = next_session(s).run_once()

    assert not result.halted
    assert result.entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_pending"
    assert s.broker.closed == ["SPY"]  # yalniz ilk gunun kapatmasi


@pytest.mark.parametrize("path", PATHS)
def test_an_old_buy_order_is_not_an_orphan_exit_for_a_long_entry(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Yon journal'dan gelir: alis girisi icin alis emri cikis degildir."""
    s = prepare(path, config, tmp_path)
    halt_on_a_late_unprotected_fill(s)
    s.broker.open_orders.append(old_exit_order(s, "new").model_copy(update={"side": Side.BUY}))
    s.broker.fail_get_order = True

    result = next_session(s).run_once()

    assert not result.halted
    assert result.entries_blocked
    assert leg_ids(s.broker) == ["leg-stop"]


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_order_list_is_not_evidence_of_an_orphan(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Onceki seans, hesap duz, emir listesi okunamiyor: gun kapanmaz, iz surer."""
    s = prepare(path, config, tmp_path)
    halt_on_a_late_unprotected_fill(s)
    runner = next_session(s)
    s.broker.fail_get_order = True

    def fail_later_order_reads(broker: RacingBroker) -> None:
        broker.fail_open_orders = True

    s.broker.on_list = fail_later_order_reads
    result = runner.run_once()

    assert not result.halted
    assert result.entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_pending"


@pytest.mark.parametrize("path", PATHS)
def test_an_adopted_unconfirmed_old_cancel_takes_the_safe_close_path(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Onceki seans, iptal DOGRULANMAMIS, giris okunamiyor: ilk turda gun kapanir."""
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1
    assert s.runner.run_once().entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_requested"
    s.broker.fail_get_order = True

    result = next_session(s).run_once()

    assert result.halted
    assert "KILL-SWITCH: iptal iletilemedi: SPY" in " ".join(result.notes)
    # Hesap genelindeki iptal bayat girisi kapsar.
    assert s.broker.open_orders == []
    assert status_of(s.conn, s.entry) == "cancel_requested"


@pytest.mark.parametrize("path", PATHS)
def test_a_rejected_cancel_of_a_filled_entry_is_not_adopted_as_unresolved(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Dolum yarisi: iptal reddedildi ama giris `filled` okundu; iz `cancel_pending`.

    Sonraki surec bunu cozumsuz istek diye devralmaz: duz hesapta tek bir
    gecici okuma hatasi gunu kapatmaz.
    """
    s = prepare(path, config, tmp_path)
    halt_on_an_unprotected_fill(s)
    s.broker.fail_get_order = True

    result = next_session(s).run_once()

    assert not result.halted
    assert result.entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_pending"


@pytest.mark.parametrize("path", PATHS)
def test_an_old_exit_order_is_orphaned_when_the_journal_time_is_unreadable(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Journal'daki gonderim ani bozuk: seans kanitlanamaz, giris eski sayilir."""
    s = prepare(path, config, tmp_path)
    halt_on_a_late_unprotected_fill(s)
    s.conn.execute(
        "UPDATE orders SET submitted_at = 'bozuk' WHERE client_order_id = ?",
        (s.entry.client_order_id,),
    )
    s.conn.commit()
    s.broker.open_orders.append(old_exit_order(s, "new"))
    s.broker.fail_get_order = True

    result = next_session(s).run_once()

    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    assert leg_ids(s.broker) == []


@pytest.mark.parametrize("path", PATHS)
def test_same_session_legs_are_not_orphans_while_the_entry_is_unreadable(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Ayni seans: girisin kendi bekleyen (`held`) bacaklari sahipsiz sayilmaz."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    stop, target = legs(s.order, stop_qty=s.order.qty)
    s.broker.open_orders.extend(
        [stop.model_copy(update={"status": "held"}), target.model_copy(update={"status": "held"})]
    )
    s.broker.fail_get_order = True

    for _ in range(3):
        result = s.runner.run_once()
        assert not result.halted
        assert result.entries_blocked
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]


@pytest.mark.parametrize("path", PATHS)
def test_same_session_legs_are_not_orphans_for_a_row_adopted_from_the_journal(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Yeni surec ayni seansin satirini journal'dan devralir; seans journal anindan okunur."""
    s = prepare(path, config, tmp_path)
    accept_without_settling(s)
    stop, target = legs(s.order, stop_qty=s.order.qty)
    s.broker.open_orders.extend(
        [stop.model_copy(update={"status": "held"}), target.model_copy(update={"status": "held"})]
    )
    s.broker.fail_get_order = True

    result = reopen(s, tmp_path).run_once()

    assert not result.halted
    assert result.entries_blocked
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert status_of(s.conn, s.entry) == "cancel_pending"


@pytest.mark.parametrize("path", PATHS)
def test_an_adopted_unconfirmed_cancel_gets_no_blind_turn(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Ulasmayan iptal + okunamayan giris: yeni surec sureyi yeniden baslatamaz."""
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1
    assert s.runner.run_once().entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_requested"
    s.broker.fail_get_order = True

    # Ayni surecte bir kor tur hakki var; gun henuz kapanmaz.
    assert not s.runner.run_once().halted
    assert [o.broker_order_id for o in s.broker.open_orders] == [s.entry.broker_order_id]

    # Yeniden baslatma: devralinan istekte kor tur hakki yok.
    result = reopen(s, tmp_path).run_once()

    assert result.halted
    assert "iptal iletilemedi: SPY" in " ".join(result.notes)
    assert s.broker.open_orders == []
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_an_adopted_unconfirmed_cancel_gets_a_single_resend(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Giris okunuyor ve aktif, ama yeniden gonderim de ulasmiyor: gun o turda kapanir."""
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1
    assert s.runner.run_once().entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_requested"
    s.broker.unreachable_cancels = 5

    result = reopen(s, tmp_path).run_once()

    assert result.halted
    assert "iptal iletilemedi: SPY" in " ".join(result.notes)
    assert s.broker.cancelled_ids.count(s.entry.broker_order_id) == 2
    assert s.broker.open_orders == []
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_an_adopted_unconfirmed_cancel_is_resent_when_the_entry_is_readable(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Karsilastirma: devralinan istekte giris okunuyor ve aktifse yeniden gonderilir."""
    s = prepare(path, config, tmp_path)
    s.broker.unreachable_cancels = 1
    assert s.runner.run_once().entries_blocked
    assert status_of(s.conn, s.entry) == "cancel_requested"

    result = reopen(s, tmp_path).run_once()

    assert not result.halted
    assert s.broker.cancelled_ids.count(s.entry.broker_order_id) == 2
    assert status_of(s.conn, s.entry) == "canceled"
