"""Mutabakat testleri.

Mutabakat, ogrenme katmanina giden veriyi uretir. Buradaki bir hata
sessizdir: sistem calismaya devam eder ama istatistikler yanlis olur
ve yanlis istatistige gore ogrenen bir sistem, ogrenmeyenden kotudur.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tlab.core.types import ExitReason, Fill, Side
from tlab.engine.reconciler import build_trade, infer_exit_reason, pair_fills

T0 = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
FLATTEN_AT = datetime(2026, 1, 5, 20, 50, tzinfo=UTC)


def fill(
    *,
    client_id: str = "tlab-entry",
    order_id: str = "o1",
    symbol: str = "SPY",
    side: Side = Side.BUY,
    qty: float = 100,
    price: float = 100.0,
    minutes: int = 0,
    order_type: str = "limit",
) -> Fill:
    return Fill(
        broker_order_id=order_id,
        client_order_id=client_id,
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        filled_at=T0 + timedelta(minutes=minutes),
        order_type=order_type,
    )


ORDER_INFO: dict[str, Any] = {
    "decision_id": "d1",
    "strategy_id": "orb",
    "params_version": "orb-abc123",
    "stop_loss": 99.0,
    "take_profit": 101.5,
    "limit_price": 100.0,
}


# --------------------------------------------------------------------------
# Eslestirme
# --------------------------------------------------------------------------


def test_entry_and_exit_are_paired() -> None:
    fills = [
        fill(client_id="tlab-entry", order_id="entry"),
        fill(client_id="leg", order_id="exit", side=Side.SELL, price=101.5, minutes=30),
    ]
    matched = pair_fills(fills, {"tlab-entry"})
    assert len(matched) == 1
    assert matched[0].entry.broker_order_id == "entry"
    assert matched[0].exit.broker_order_id == "exit"
    assert matched[0].qty == pytest.approx(100)


def test_fills_from_other_sources_are_ignored() -> None:
    """Elle acilmis pozisyonlar bizim istatistiklerimizi kirletmemeli."""
    fills = [
        fill(client_id="manuel-emir", order_id="x"),
        fill(client_id="manuel-cikis", order_id="y", side=Side.SELL, minutes=10),
    ]
    assert pair_fills(fills, {"tlab-entry"}) == []


def test_open_position_produces_no_trade() -> None:
    """Henuz kapanmamis pozisyon kayda gecmez."""
    assert pair_fills([fill(client_id="tlab-entry")], {"tlab-entry"}) == []


def test_symbols_are_matched_independently() -> None:
    fills = [
        fill(client_id="tlab-a", order_id="a1", symbol="SPY"),
        fill(client_id="tlab-b", order_id="b1", symbol="AAPL", minutes=1),
        fill(client_id="leg", order_id="b2", symbol="AAPL", side=Side.SELL, minutes=5),
        fill(client_id="leg", order_id="a2", symbol="SPY", side=Side.SELL, minutes=9),
    ]
    matched = pair_fills(fills, {"tlab-a", "tlab-b"})
    assert {m.entry.symbol for m in matched} == {"SPY", "AAPL"}
    by_symbol = {m.entry.symbol: m for m in matched}
    assert by_symbol["SPY"].exit.broker_order_id == "a2"
    assert by_symbol["AAPL"].exit.broker_order_id == "b2"


def test_fills_are_ordered_by_time_not_by_input_order() -> None:
    """Broker'in dondurdugu sira garanti degil; zaman sirasi esastir."""
    fills = [
        fill(client_id="leg", order_id="exit", side=Side.SELL, minutes=30),
        fill(client_id="tlab-entry", order_id="entry", minutes=0),
    ]
    matched = pair_fills(fills, {"tlab-entry"})
    assert len(matched) == 1
    assert matched[0].entry.broker_order_id == "entry"


def test_partial_exit_closes_only_what_it_covers() -> None:
    fills = [
        fill(client_id="tlab-entry", order_id="entry", qty=100),
        fill(client_id="leg", order_id="exit1", side=Side.SELL, qty=40, minutes=5),
        fill(client_id="leg", order_id="exit2", side=Side.SELL, qty=60, minutes=9),
    ]
    matched = pair_fills(fills, {"tlab-entry"})
    assert [m.qty for m in matched] == [40, 60]


def test_trade_id_is_derived_not_random() -> None:
    """Mutabakat her turda ayni islemi gorur; kayit bir kez dusmeli."""
    fills = [
        fill(client_id="tlab-entry", order_id="entry"),
        fill(client_id="leg", order_id="exit", side=Side.SELL, minutes=30),
    ]
    first = pair_fills(fills, {"tlab-entry"})[0]
    second = pair_fills(list(reversed(fills)), {"tlab-entry"})[0]
    assert first.trade_id == second.trade_id
    assert len(first.trade_id) == 32


# --------------------------------------------------------------------------
# Cikis sebebi
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("order_type", "minutes", "expected"),
    [
        ("limit", 30, ExitReason.TARGET),
        ("stop", 30, ExitReason.STOP),
        ("stop_limit", 30, ExitReason.STOP),
        ("market", 30, ExitReason.MANUAL),
        ("market", 400, ExitReason.EOD_FLATTEN),
    ],
)
def test_exit_reason_inference(order_type: str, minutes: int, expected: ExitReason) -> None:
    exit_fill = fill(side=Side.SELL, order_type=order_type, minutes=minutes)
    assert infer_exit_reason(exit_fill, FLATTEN_AT) is expected


def test_exit_reason_without_flatten_anchor() -> None:
    assert infer_exit_reason(fill(order_type="market"), None) is ExitReason.MANUAL


# --------------------------------------------------------------------------
# Islem kaydi
# --------------------------------------------------------------------------


def test_winning_trade_is_built_correctly() -> None:
    matched = pair_fills(
        [
            fill(client_id="tlab-entry", order_id="entry", price=100.0),
            fill(
                client_id="leg",
                order_id="exit",
                side=Side.SELL,
                price=101.5,
                minutes=30,
                order_type="limit",
            ),
        ],
        {"tlab-entry"},
    )[0]

    trade = build_trade(matched, ORDER_INFO, run_id="run-1", flatten_at=FLATTEN_AT)
    assert trade.symbol == "SPY"
    assert trade.strategy_id == "orb"
    assert trade.params_version == "orb-abc123"
    assert trade.decision_id == "d1"
    assert trade.exit_reason is ExitReason.TARGET
    assert trade.net_pnl == pytest.approx(150.0)
    assert trade.r_multiple == pytest.approx(1.5)
    assert trade.holding_seconds == 1800


def test_losing_trade_is_minus_one_r() -> None:
    matched = pair_fills(
        [
            fill(client_id="tlab-entry", order_id="entry", price=100.0),
            fill(
                client_id="leg",
                order_id="exit",
                side=Side.SELL,
                price=99.0,
                minutes=12,
                order_type="stop",
            ),
        ],
        {"tlab-entry"},
    )[0]

    trade = build_trade(matched, ORDER_INFO, run_id="run-1", flatten_at=FLATTEN_AT)
    assert trade.exit_reason is ExitReason.STOP
    assert trade.net_pnl == pytest.approx(-100.0)
    assert trade.r_multiple == pytest.approx(-1.0)


def test_short_trade_pnl_sign() -> None:
    matched = pair_fills(
        [
            fill(client_id="tlab-entry", order_id="entry", side=Side.SELL, price=100.0),
            fill(client_id="leg", order_id="exit", side=Side.BUY, price=98.5, minutes=20),
        ],
        {"tlab-entry"},
    )[0]
    info = dict(ORDER_INFO, stop_loss=101.0, take_profit=98.5)
    trade = build_trade(matched, info, run_id="run-1")
    assert trade.side is Side.SELL
    assert trade.net_pnl == pytest.approx(150.0)


# --------------------------------------------------------------------------
# Slippage
# --------------------------------------------------------------------------


def test_entry_slippage_is_positive_when_we_pay_more_than_planned() -> None:
    """Isaret her zaman maliyet yonunde: pozitif = aleyhimize."""
    matched = pair_fills(
        [
            fill(client_id="tlab-entry", order_id="entry", price=100.10),
            fill(client_id="leg", order_id="exit", side=Side.SELL, price=101.5, minutes=30),
        ],
        {"tlab-entry"},
    )[0]
    trade = build_trade(matched, ORDER_INFO, run_id="run-1")
    # Planlanan 100,00; gerceklesen 100,10 -> 10 bps maliyet
    assert trade.entry_slippage_bps == pytest.approx(10.0)


def test_entry_slippage_is_negative_when_we_pay_less() -> None:
    matched = pair_fills(
        [
            fill(client_id="tlab-entry", order_id="entry", price=99.90),
            fill(client_id="leg", order_id="exit", side=Side.SELL, price=101.5, minutes=30),
        ],
        {"tlab-entry"},
    )[0]
    trade = build_trade(matched, ORDER_INFO, run_id="run-1")
    assert trade.entry_slippage_bps == pytest.approx(-10.0)


def test_short_entry_slippage_uses_the_same_cost_convention() -> None:
    """Satarken planlanandan ucuza girmek de maliyettir."""
    matched = pair_fills(
        [
            fill(client_id="tlab-entry", order_id="entry", side=Side.SELL, price=99.90),
            fill(client_id="leg", order_id="exit", side=Side.BUY, price=98.5, minutes=20),
        ],
        {"tlab-entry"},
    )[0]
    info = dict(ORDER_INFO, stop_loss=101.0, take_profit=98.5)
    trade = build_trade(matched, info, run_id="run-1")
    assert trade.entry_slippage_bps == pytest.approx(10.0)


def test_market_entry_has_no_slippage_reference() -> None:
    """Limit fiyati yoksa karsilastirilacak bir plan da yoktur."""
    matched = pair_fills(
        [
            fill(client_id="tlab-entry", order_id="entry", price=100.0, order_type="market"),
            fill(client_id="leg", order_id="exit", side=Side.SELL, price=101.5, minutes=30),
        ],
        {"tlab-entry"},
    )[0]
    trade = build_trade(matched, dict(ORDER_INFO, limit_price=None), run_id="run-1")
    assert trade.entry_slippage_bps is None


def test_unknown_strategy_falls_back_without_crashing() -> None:
    """Eski bir emir icin karar kaydi yoksa islem yine de kaydedilmeli."""
    matched = pair_fills(
        [
            fill(client_id="tlab-entry", order_id="entry"),
            fill(client_id="leg", order_id="exit", side=Side.SELL, price=101.5, minutes=30),
        ],
        {"tlab-entry"},
    )[0]
    bare = {"stop_loss": 99.0, "take_profit": 101.5}
    trade = build_trade(matched, bare, run_id="run-1")
    assert trade.strategy_id == "unknown"
    assert trade.decision_id is None
