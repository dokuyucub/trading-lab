"""Bayat giris iptali ile dolum arasindaki yaris (Codex #63/6777889127).

Runner turun basinda pozisyonlari okur (SPY yok), sonra bekleyen
girisi gorur ve iptal ister. Giris bu iki an arasinda dolabilir. O
zaman brokerda koruma bacaklari da acik emir olarak gorunur. Sembol
bazli iptal o anda gorunen her emri duserdi.

Buradaki sahte broker yarisi tam o noktada, iptal cagrisinin ICINDE
ve iptalden ONCE uretir. Beklenen davranis:
  * iptal yalnizca girisin kendi kimligine gider; bacak kimligi hicbir
    senaryoda iptal cagrisina girmez;
  * sonuc brokerdan yeniden okunur: dolan miktari stop bacaklari
    kapsiyorsa bacaklara dokunulmaz, kapsamiyorsa ya da okunamiyorsa
    gun kill-switch ile kapanir (fail-closed);
  * reddedilen iptal "canceled" yazilmaz.

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
from tlab.journal.db import apply_migrations, connect
from tlab.journal.queries import halt_reason

PATHS = ["ttl", "blocked"]


@dataclass
class RacingBroker(FakeBroker):
    """Iptal cagrisinin icinde, iptalden once broker durumunu degistirir."""

    race: Callable[[RacingBroker], None] | None = None

    def cancel_order(self, broker_order_id: str) -> None:
        if self.race is not None:
            race, self.race = self.race, None
            race(self)
        super().cancel_order(broker_order_id)


@dataclass
class Setup:
    broker: RacingBroker
    conn: sqlite3.Connection
    runner: SessionRunner
    entry: OrderRef
    order: BracketOrder


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
    if stale:
        runner = first
    else:
        conn.execute("DROP TABLE daily_state")
        runner = build_runner(config=config, conn=conn, broker=broker, market=market)
    return Setup(broker=broker, conn=conn, runner=runner, entry=entry, order=order)


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


def fill(broker: RacingBroker, entry: OrderRef, order: BracketOrder, qty: float) -> None:
    broker.positions = [
        Position(
            symbol=order.symbol,
            side=Side.BUY,
            qty=qty,
            avg_entry_price=order.limit_price or 100.0,
            current_price=order.limit_price or 100.0,
        )
    ]
    if qty >= order.qty:
        broker.open_orders = [
            o for o in broker.open_orders if o.broker_order_id != entry.broker_order_id
        ]


def status_of(conn: sqlite3.Connection, entry: OrderRef) -> str:
    row = conn.execute(
        "SELECT status FROM orders WHERE client_order_id = ?", (entry.client_order_id,)
    ).fetchone()
    return str(row[0])


def leg_ids(broker: FakeBroker) -> list[str]:
    return sorted(
        o.broker_order_id for o in broker.open_orders if o.broker_order_id.startswith("leg-")
    )


# --------------------------------------------------------------------------
# Dolan miktar korunuyor: bacaklara dokunulmaz
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", PATHS)
def test_a_partial_fill_during_cancel_keeps_the_legs(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)
    filled = s.order.qty // 2

    def partial(broker: RacingBroker) -> None:
        fill(broker, s.entry, s.order, filled)
        broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty))

    s.broker.race = partial
    result = s.runner.run_once()

    # Iptal yalnizca girisin kimligine gitti; kalan miktar iptal edildi.
    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert s.broker.cancelled == []
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert s.broker.closed == []
    assert not result.halted
    assert result.cancelled == 0
    assert status_of(s.conn, s.entry) != "canceled"
    assert any("iptal sirasinda doldu" in note for note in result.notes)
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_a_full_fill_refuses_the_cancel_and_keeps_the_legs(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)

    def full(broker: RacingBroker) -> None:
        fill(broker, s.entry, s.order, s.order.qty)
        broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty))

    s.broker.race = full
    result = s.runner.run_once()

    # Dolmus girisin iptali reddedildi; baska kimlige iptal gitmedi.
    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert s.broker.cancelled == []
    assert leg_ids(s.broker) == ["leg-stop", "leg-target"]
    assert s.broker.closed == []
    assert not result.halted
    assert status_of(s.conn, s.entry) != "canceled"
    assert len(s.broker.submitted) == 1


# --------------------------------------------------------------------------
# Koruma dogrulanamiyor: gun kapanir
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("cover", ["none", "short"])
def test_an_unprotected_fill_halts_the_day(
    path: str, cover: str, config: Config, tmp_path: Path
) -> None:
    """Bacak gorunmuyor ya da stop bacagi dolan miktardan az."""
    s = prepare(path, config, tmp_path)

    def unprotected(broker: RacingBroker) -> None:
        fill(broker, s.entry, s.order, s.order.qty)
        if cover == "short":
            broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty - 1))

    s.broker.race = unprotected
    result = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert result.halted
    assert "KILL-SWITCH: koruma dogrulanamadi: SPY" in " ".join(result.notes)
    # Kapatma once butun emirleri iptal eder, sonra pozisyonu kapatir.
    assert s.broker.cancelled == [None]
    assert s.broker.closed == ["SPY"]
    assert result.flattened == 1
    assert result.evaluated == 0
    if path == "ttl":
        assert halt_reason(s.conn, result.now.date()) is not None

    # Karar ayni surecte kalicidir: sonraki tur da gunu kapali bilir.
    assert s.runner.run_once().halted
    assert len(s.broker.submitted) == 1


@pytest.mark.parametrize("path", PATHS)
def test_an_unreadable_broker_after_cancel_halts_and_retries_the_flatten(
    path: str, config: Config, tmp_path: Path
) -> None:
    s = prepare(path, config, tmp_path)

    def blind(broker: RacingBroker) -> None:
        fill(broker, s.entry, s.order, s.order.qty)
        broker.open_orders.extend(legs(s.order, stop_qty=s.order.qty))
        broker.fail_open_orders = True

    s.broker.race = blind
    result = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert result.halted
    assert s.broker.closed == []

    s.broker.fail_open_orders = False
    retry = s.runner.run_once()
    assert retry.halted
    assert s.broker.closed == ["SPY"]
    assert len(s.broker.submitted) == 1


# --------------------------------------------------------------------------
# Dolum yok
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", PATHS)
def test_a_refused_cancel_without_a_fill_is_not_written_as_canceled(
    path: str, config: Config, tmp_path: Path
) -> None:
    """Giris brokerda baska yoldan kapanmis (ornek: suresi dolmus); iptal reddedildi."""
    s = prepare(path, config, tmp_path)

    def vanished(broker: RacingBroker) -> None:
        broker.open_orders = []

    s.broker.race = vanished
    result = s.runner.run_once()

    assert s.broker.cancelled_ids == [s.entry.broker_order_id]
    assert result.cancelled == 0
    assert not result.halted
    assert s.broker.closed == []
    assert status_of(s.conn, s.entry) != "canceled"


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
