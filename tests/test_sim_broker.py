"""Simulasyon brokeri testleri.

Buradaki testlerin cogu tek bir seyi dogruluyor: simulasyon KENDINE
AVANTAJ SAGLAMIYOR. Iyimser bir dolum modeli, canliya gecince
kaybolan bir karlilik gosterir - ve bu, hic backtest yapmamaktan
zararlidir cunku yanlis bir guven verir.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tlab.backtest.sim_broker import SimBroker, SimFillModel
from tlab.core.types import Bar, BracketOrder, EntryType, Side
from tlab.errors import BrokerError

T0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)


def bar(
    *, open_: float, high: float, low: float, close: float, minute: int = 0, symbol: str = "SPY"
) -> Bar:
    return Bar(
        symbol=symbol,
        ts=T0 + timedelta(minutes=minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=10_000,
    )


def long_order(
    *, limit: float = 100.0, stop: float = 99.0, target: float = 101.5, qty: int = 100
) -> BracketOrder:
    return BracketOrder(
        symbol="SPY",
        side=Side.BUY,
        qty=qty,
        entry_type=EntryType.LIMIT,
        limit_price=limit,
        stop_loss=stop,
        take_profit=target,
    )


@pytest.fixture
def broker() -> SimBroker:
    sim = SimBroker(starting_equity=100_000.0, fill_model=SimFillModel(slippage_bps=0.0))
    sim.set_clock(is_open=True, now=T0, next_open=T0, next_close=T0 + timedelta(hours=6))
    return sim


# --------------------------------------------------------------------------
# Giris dolumu
# --------------------------------------------------------------------------


def test_limit_order_does_not_fill_on_a_mere_touch(broker: SimBroker) -> None:
    """Fiyata degip donen barda sirada onumuzde kimse yokmus gibi davranmiyoruz."""
    broker.submit_bracket(long_order(limit=100.0))
    broker.advance(bar(open_=100.5, high=100.6, low=100.0, close=100.4))
    assert broker.get_positions() == []


def test_limit_order_fills_when_price_penetrates(broker: SimBroker) -> None:
    broker.submit_bracket(long_order(limit=100.0))
    broker.advance(bar(open_=100.5, high=100.6, low=99.8, close=100.2))
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].avg_entry_price == pytest.approx(100.0)


def test_fill_never_better_than_the_limit(broker: SimBroker) -> None:
    """Bar limitin cok altinda acilsa bile giris limit fiyatindan.

    Gercekte gap'te daha iyi fiyat alinabilir; iyimserligi
    simulasyona sokmamak icin bu avantaji saymiyoruz.
    """
    broker.submit_bracket(long_order(limit=100.0))
    broker.advance(bar(open_=98.0, high=99.0, low=97.5, close=98.5))
    assert broker.get_positions()[0].avg_entry_price == pytest.approx(100.0)


def test_slippage_is_applied_against_us() -> None:
    sim = SimBroker(fill_model=SimFillModel(slippage_bps=10.0))
    sim.set_clock(is_open=True, now=T0, next_open=T0, next_close=T0)
    sim.submit_bracket(long_order(limit=100.0))
    sim.advance(bar(open_=100.5, high=100.6, low=99.8, close=100.2))
    # Alirken 10 bps daha pahali
    assert sim.get_positions()[0].avg_entry_price == pytest.approx(100.1)


def test_duplicate_order_for_the_same_symbol_is_rejected(broker: SimBroker) -> None:
    broker.submit_bracket(long_order())
    with pytest.raises(BrokerError, match="zaten acik"):
        broker.submit_bracket(long_order())


# --------------------------------------------------------------------------
# Cikis dolumu
# --------------------------------------------------------------------------


def fill_entry(broker: SimBroker) -> None:
    broker.submit_bracket(long_order(limit=100.0, stop=99.0, target=101.5))
    broker.advance(bar(open_=100.5, high=100.6, low=99.8, close=100.2))


def test_entry_and_exit_never_happen_in_the_same_bar(broker: SimBroker) -> None:
    """Giris ve cikisin ayni barda olmasi gercekci degil.

    Ayni barda ikisini birden saymak, gercekte olmasi cok zor bir
    kazanci ucretsiz sayardi.
    """
    broker.submit_bracket(long_order(limit=100.0, target=101.5))
    broker.advance(bar(open_=100.5, high=102.0, low=99.8, close=101.8))
    assert len(broker.get_positions()) == 1, "cikis bir sonraki bara birakilmali"


def test_target_exit(broker: SimBroker) -> None:
    fill_entry(broker)
    broker.advance(bar(open_=100.5, high=102.0, low=100.4, close=101.8, minute=1))
    assert broker.get_positions() == []
    assert broker.realized_pnl == pytest.approx(150.0)


def test_stop_exit(broker: SimBroker) -> None:
    fill_entry(broker)
    broker.advance(bar(open_=100.0, high=100.1, low=98.5, close=98.8, minute=1))
    assert broker.get_positions() == []
    assert broker.realized_pnl == pytest.approx(-100.0)


def test_stop_wins_when_both_are_hit_in_one_bar(broker: SimBroker) -> None:
    """Bar icindeki siralamayi bilmiyoruz; bilmedigimiz yerde aleyhimize seciyoruz."""
    fill_entry(broker)
    broker.advance(bar(open_=100.2, high=102.0, low=98.5, close=101.0, minute=1))
    assert broker.realized_pnl < 0, "iki taraf da tetiklendiyse stop kabul edilmeli"


def test_gap_through_the_stop_fills_at_the_worse_price(broker: SimBroker) -> None:
    """Stop bir GARANTI degil, tetikleyicidir.

    Fiyat stop'un altinda acarsa cikis o acilistan olur; stop
    fiyatindan cikildigini varsaymak gercek riski gizler.
    """
    fill_entry(broker)
    broker.advance(bar(open_=95.0, high=95.5, low=94.0, close=94.5, minute=1))
    assert broker.realized_pnl == pytest.approx(-500.0)  # 100 -> 95, 100 adet


def test_gap_beyond_the_target_does_not_pay_more(broker: SimBroker) -> None:
    """Limit emri hedefin otesinde dolmaz."""
    fill_entry(broker)
    broker.advance(bar(open_=105.0, high=106.0, low=104.5, close=105.5, minute=1))
    assert broker.realized_pnl == pytest.approx(150.0)  # 101.5'ten, 105'ten degil


def test_short_position_pnl_sign() -> None:
    sim = SimBroker(fill_model=SimFillModel(slippage_bps=0.0))
    sim.set_clock(is_open=True, now=T0, next_open=T0, next_close=T0)
    sim.submit_bracket(
        BracketOrder(
            symbol="SPY",
            side=Side.SELL,
            qty=100,
            entry_type=EntryType.LIMIT,
            limit_price=100.0,
            stop_loss=101.0,
            take_profit=98.5,
        )
    )
    sim.advance(bar(open_=99.5, high=100.3, low=99.4, close=100.1))
    assert len(sim.get_positions()) == 1
    sim.advance(bar(open_=99.0, high=99.2, low=98.0, close=98.2, minute=1))
    assert sim.realized_pnl == pytest.approx(150.0)


# --------------------------------------------------------------------------
# Hesap durumu
# --------------------------------------------------------------------------


def test_equity_tracks_unrealized_profit(broker: SimBroker) -> None:
    fill_entry(broker)
    broker.advance(bar(open_=100.5, high=101.0, low=100.4, close=101.0, minute=1))
    # Hedef 101.5, henuz kapanmadi: 1,00 x 100 adet gerceklesmemis kar
    assert broker.equity == pytest.approx(100_100.0)


def test_buying_power_excludes_open_exposure(broker: SimBroker) -> None:
    """Marj yok: acik maruziyet alim gucunden dusuluyor.

    Kaldirac varsaymak, backtest'i gercekte alinamayacak
    pozisyonlarla sisirir.
    """
    before = broker.get_account().buying_power
    fill_entry(broker)
    after = broker.get_account().buying_power
    assert after == pytest.approx(before - 100 * 100.0, abs=50)


def test_day_start_resets_the_daily_reference(broker: SimBroker) -> None:
    fill_entry(broker)
    broker.advance(bar(open_=100.5, high=102.0, low=100.4, close=101.8, minute=1))
    broker.start_day()
    assert broker.get_account().daily_pl == pytest.approx(0.0)


def test_close_position_and_cancel(broker: SimBroker) -> None:
    fill_entry(broker)
    assert broker.close_position("SPY") is not None
    assert broker.get_positions() == []
    assert broker.close_position("SPY") is None

    broker.submit_bracket(long_order(limit=95.0, stop=94.0, target=97.0))
    assert broker.cancel_open_orders("SPY") == 1
    assert broker.list_open_orders() == []


def test_fills_are_recorded_for_reconciliation(broker: SimBroker) -> None:
    fill_entry(broker)
    broker.advance(bar(open_=100.5, high=102.0, low=100.4, close=101.8, minute=1))
    fills = broker.list_fills(T0 - timedelta(days=1))
    assert [f.side for f in fills] == [Side.BUY, Side.SELL]
    assert fills[0].order_type == "limit"


def test_open_orders_include_protective_legs(broker: SimBroker) -> None:
    """Dolmus bir girisin koruma bacaklari da acik emirdir.

    Dongu bu bilgiyi sembolun mesgul oldugunu anlamak icin kullaniyor.
    """
    fill_entry(broker)
    assert [ref.symbol for ref in broker.list_open_orders()] == ["SPY"]
