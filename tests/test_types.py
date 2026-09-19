"""Cekirdek tiplerin dogrulama kurallari.

Buradaki testlerin cogu "hatali nesne olusturulamaz" iddiasini
dogrular. Amac: bozuk bir emrin brokera ulasma ihtimalini sifirlamak.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tlab.core.types import (
    Account,
    Bar,
    BracketOrder,
    Decision,
    EntryType,
    GateVerdict,
    Intent,
    Position,
    Quote,
    Side,
    round_price,
)

TS = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


# --------------------------------------------------------------------------
# Side
# --------------------------------------------------------------------------


def test_side_opposite_and_sign() -> None:
    assert Side.BUY.opposite is Side.SELL
    assert Side.SELL.opposite is Side.BUY
    assert Side.BUY.sign == 1
    assert Side.SELL.sign == -1


# --------------------------------------------------------------------------
# Bar
# --------------------------------------------------------------------------


def test_bar_accepts_valid_ohlc() -> None:
    bar = Bar(symbol="SPY", ts=TS, open=100, high=101, low=99, close=100.5, volume=1000)
    assert bar.range == pytest.approx(2.0)


def test_bar_is_immutable() -> None:
    bar = Bar(symbol="SPY", ts=TS, open=100, high=101, low=99, close=100.5, volume=1000)
    with pytest.raises(ValidationError):
        bar.close = 200  # type: ignore[misc]


@pytest.mark.parametrize(
    ("open_", "high", "low", "close"),
    [
        (100, 99, 99.5, 100.5),  # high < low
        (100, 100.5, 99, 101),  # close, high'in ustunde
        (98, 101, 99, 100),  # open, low'un altinda
    ],
)
def test_bar_rejects_impossible_ohlc(open_: float, high: float, low: float, close: float) -> None:
    with pytest.raises(ValidationError):
        Bar(symbol="X", ts=TS, open=open_, high=high, low=low, close=close, volume=1)


def test_bar_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        Bar(
            symbol="X",
            ts=datetime(2026, 1, 5, 14, 30),
            open=100,
            high=101,
            low=99,
            close=100,
            volume=1,
        )


def test_bar_rejects_negative_price() -> None:
    with pytest.raises(ValidationError):
        Bar(symbol="X", ts=TS, open=-1, high=101, low=99, close=100, volume=1)


# --------------------------------------------------------------------------
# Quote
# --------------------------------------------------------------------------


def test_quote_spread_in_basis_points() -> None:
    quote = Quote(symbol="SPY", ts=TS, bid=100.0, ask=100.02)
    assert quote.mid == pytest.approx(100.01)
    assert quote.spread_bps == pytest.approx(2.0, abs=0.01)
    assert not quote.is_crossed


def test_quote_flags_crossed_market_without_raising() -> None:
    """Capraz piyasa gercek bir durum: hata firlatmak sistemi cokertirdi.

    Bayrak olarak isaretlenir, risk kapisi gorup islem yapmaz.
    """
    quote = Quote(symbol="SPY", ts=TS, bid=100.05, ask=100.00)
    assert quote.is_crossed


# --------------------------------------------------------------------------
# Intent
# --------------------------------------------------------------------------


def test_intent_computes_reward_risk(sample_intent: Intent) -> None:
    assert sample_intent.risk_per_share == pytest.approx(1.0)
    assert sample_intent.reward_per_share == pytest.approx(1.5)
    assert sample_intent.reward_risk == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("side", "reference", "stop", "target"),
    [
        (Side.BUY, 100.0, 101.0, 102.0),  # long'da stop girisin ustunde
        (Side.BUY, 100.0, 99.0, 99.5),  # long'da hedef girisin altinda
        (Side.SELL, 100.0, 99.0, 98.0),  # short'ta stop girisin altinda
        (Side.SELL, 100.0, 101.0, 101.5),  # short'ta hedef girisin ustunde
    ],
)
def test_intent_rejects_inverted_bracket(
    side: Side, reference: float, stop: float, target: float
) -> None:
    """Ters bracket girisle birlikte stop'u tetikler: brokera hic gitmemeli."""
    with pytest.raises(ValidationError):
        Intent(
            strategy_id="t",
            symbol="SPY",
            side=side,
            reference_price=reference,
            stop_loss=stop,
            take_profit=target,
        )


def test_intent_accepts_valid_short() -> None:
    intent = Intent(
        strategy_id="t",
        symbol="SPY",
        side=Side.SELL,
        reference_price=100.0,
        stop_loss=101.0,
        take_profit=98.0,
    )
    assert intent.reward_risk == pytest.approx(2.0)


def test_intent_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        Intent(
            strategy_id="t",
            symbol="SPY",
            side=Side.BUY,
            reference_price=100.0,
            stop_loss=99.0,
            take_profit=101.0,
            confidence=1.5,
        )


# --------------------------------------------------------------------------
# GateVerdict
# --------------------------------------------------------------------------


def test_allow_requires_positive_quantity() -> None:
    assert GateVerdict.allow(10).qty == 10
    with pytest.raises(ValueError, match="pozitif olmali"):
        GateVerdict.allow(0)


def test_veto_requires_a_reason() -> None:
    """Sebepsiz veto, ogrenme katmani icin degersiz bir kayittir."""
    verdict = GateVerdict.veto("spread cok genis")
    assert not verdict.allowed
    assert verdict.vetoes == ("spread cok genis",)
    with pytest.raises(ValueError, match="en az bir sebep"):
        GateVerdict.veto()


# --------------------------------------------------------------------------
# BracketOrder
# --------------------------------------------------------------------------


def test_bracket_order_from_intent_rounds_prices() -> None:
    intent = Intent(
        strategy_id="t",
        symbol="SPY",
        side=Side.BUY,
        reference_price=100.123456,
        stop_loss=99.987654,
        take_profit=101.555555,
    )
    order = BracketOrder.from_intent(intent, qty=10, entry_type=EntryType.LIMIT)
    assert order.limit_price == 100.12
    assert order.stop_loss == 99.99
    assert order.take_profit == 101.56
    assert order.client_order_id.startswith("tlab-")


def test_market_entry_must_not_carry_limit_price() -> None:
    with pytest.raises(ValidationError):
        BracketOrder(
            symbol="SPY",
            side=Side.BUY,
            qty=1,
            entry_type=EntryType.MARKET,
            limit_price=100.0,
            stop_loss=99.0,
            take_profit=101.0,
        )


def test_limit_entry_requires_limit_price() -> None:
    with pytest.raises(ValidationError):
        BracketOrder(
            symbol="SPY",
            side=Side.BUY,
            qty=1,
            entry_type=EntryType.LIMIT,
            stop_loss=99.0,
            take_profit=101.0,
        )


def test_order_quantity_must_be_whole_and_positive() -> None:
    with pytest.raises(ValidationError):
        BracketOrder(
            symbol="SPY",
            side=Side.BUY,
            qty=0,
            entry_type=EntryType.MARKET,
            stop_loss=99.0,
            take_profit=101.0,
        )


def test_client_order_ids_are_unique() -> None:
    """Ayni client_order_id ikinci kez gonderilirse broker emri reddeder."""
    ids = {
        BracketOrder(
            symbol="SPY",
            side=Side.BUY,
            qty=1,
            entry_type=EntryType.MARKET,
            stop_loss=99.0,
            take_profit=101.0,
        ).client_order_id
        for _ in range(100)
    }
    assert len(ids) == 100


# --------------------------------------------------------------------------
# Account / Position
# --------------------------------------------------------------------------


def test_account_daily_pl() -> None:
    account = Account(equity=101_000, last_equity=100_000, cash=50_000, buying_power=200_000)
    assert account.daily_pl == pytest.approx(1_000)
    assert account.daily_pl_pct == pytest.approx(1.0)
    assert account.is_healthy


def test_blocked_account_is_not_healthy() -> None:
    account = Account(
        equity=1000, last_equity=1000, cash=1000, buying_power=1000, trading_blocked=True
    )
    assert not account.is_healthy


def test_position_values() -> None:
    position = Position(
        symbol="SPY", side=Side.BUY, qty=10, avg_entry_price=100.0, current_price=102.0
    )
    assert position.cost_basis == pytest.approx(1000.0)
    assert position.market_value == pytest.approx(1020.0)


def test_position_quantity_must_be_positive() -> None:
    """Yon `side` alaninda tutulur; negatif miktar belirsizlik yaratirdi."""
    with pytest.raises(ValidationError):
        Position(symbol="SPY", side=Side.SELL, qty=-5, avg_entry_price=100.0, current_price=102.0)


# --------------------------------------------------------------------------
# Decision
# --------------------------------------------------------------------------


def test_decision_row_is_flat_and_complete(sample_intent: Intent) -> None:
    decision = Decision(run_id="r1", ts=TS, intent=sample_intent, verdict=GateVerdict.allow(25))
    row = decision.to_row()
    assert row["symbol"] == "SPY"
    assert row["allowed"] == 1
    assert row["qty"] == 25
    assert row["reward_risk"] == pytest.approx(1.5)
    assert all(not isinstance(value, dict | list) for value in row.values())


def test_vetoed_decision_cannot_carry_an_order(sample_intent: Intent) -> None:
    from tlab.core.types import OrderRef

    order = OrderRef(
        broker_order_id="b1",
        client_order_id="c1",
        symbol="SPY",
        submitted_at=TS,
        status="accepted",
    )
    with pytest.raises(ValidationError):
        Decision(
            run_id="r1",
            ts=TS,
            intent=sample_intent,
            verdict=GateVerdict.veto("test"),
            order=order,
        )


# --------------------------------------------------------------------------
# round_price
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(100.123456, 100.12), (1.0, 1.0), (0.987654, 0.9877), (0.00012345, 0.0001)],
)
def test_round_price_follows_tick_rules(raw: float, expected: float) -> None:
    assert round_price(raw) == expected
