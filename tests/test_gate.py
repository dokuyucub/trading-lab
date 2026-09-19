"""Risk kapisi testleri.

Bu dosya sistemin en onemli testlerini icerir. Kapi, gozetimsiz
calisan bir sistemde tek gercek koruma katmani: stratejinin hatasi
en fazla kotu bir islem acar, kapinin hatasi hesabi bosaltir.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import SESSION_OPEN, make_account, make_context, make_quote, make_session
from tlab.config import RiskSection
from tlab.core.types import Intent, Position, Side
from tlab.features.context import Context
from tlab.risk.gate import RiskGate, daily_loss_breached, gross_exposure


def make_intent(
    *, symbol: str = "SPY", price: float = 100.0, stop: float = 99.0, side: Side = Side.BUY
) -> Intent:
    """Hisse basi riski 1,00 olan saglikli bir niyet."""
    distance = abs(price - stop)
    return Intent(
        strategy_id="orb",
        params_version="orb-test",
        symbol=symbol,
        side=side,
        reference_price=price,
        stop_loss=stop,
        take_profit=price + 1.5 * distance if side is Side.BUY else price - 1.5 * distance,
    )


def other_position(symbol: str, *, qty: int = 10, price: float = 100.0) -> Position:
    return Position(
        symbol=symbol, side=Side.BUY, qty=qty, avg_entry_price=price, current_price=price
    )


@pytest.fixture
def gate(risk_config: RiskSection) -> RiskGate:
    return RiskGate(risk_config)


def vetoed_for(verdict_reasons: tuple[str, ...], fragment: str) -> bool:
    return any(fragment in reason for reason in verdict_reasons)


# --------------------------------------------------------------------------
# Mutlu yol ve boyutlandirma
# --------------------------------------------------------------------------


def test_healthy_intent_is_sized_from_the_risk_budget(gate: RiskGate) -> None:
    """Boyut 'ne kadar alabilirim'den degil 'ne kadar kaybederim'den turetilir."""
    verdict = gate.evaluate(make_intent(), make_context())
    # 100.000 ozsermaye * %0,5 = 500 risk butcesi; hisse basi risk 1,00 -> 500 adet
    assert verdict.allowed
    assert verdict.qty == 500


def test_wider_stop_means_smaller_position(gate: RiskGate) -> None:
    """Risk bazli boyutlandirmanin asil amaci: her islem ayni riski tasir."""
    narrow = gate.evaluate(make_intent(stop=99.0), make_context())
    wide = gate.evaluate(make_intent(stop=95.0), make_context())
    assert narrow.qty == 500  # risk 1,00
    assert wide.qty == 100  # risk 5,00
    # Ikisinin de toplam riski ayni: 500 birim
    assert narrow.qty * 1.0 == pytest.approx(wide.qty * 5.0)


def test_short_intent_is_sized_the_same_way(gate: RiskGate) -> None:
    verdict = gate.evaluate(make_intent(side=Side.SELL, stop=101.0), make_context())
    assert verdict.allowed
    assert verdict.qty == 500


# --------------------------------------------------------------------------
# Hesap durumu
# --------------------------------------------------------------------------


def test_blocked_account_is_vetoed(gate: RiskGate) -> None:
    ctx = make_context(account=make_account(trading_blocked=True))
    verdict = gate.evaluate(make_intent(), ctx)
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "islem yapmaya kapali")


def test_daily_loss_limit_stops_new_entries(gate: RiskGate) -> None:
    """Kotu bir gunu erken kapatmak, felakete donusmesini beklemekten iyidir."""
    ctx = make_context(account=make_account(equity=97_000, last_equity=100_000))
    verdict = gate.evaluate(make_intent(), ctx)
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "gunluk zarar siniri")


def test_daily_loss_helper_matches_the_threshold(risk_config: RiskSection) -> None:
    assert daily_loss_breached(make_account(equity=98_000, last_equity=100_000), risk_config)
    assert daily_loss_breached(make_account(equity=97_999, last_equity=100_000), risk_config)
    assert not daily_loss_breached(make_account(equity=98_001, last_equity=100_000), risk_config)


# --------------------------------------------------------------------------
# Seans ve pozisyon sinirlari
# --------------------------------------------------------------------------


@pytest.mark.parametrize("minutes", [5, 385, 400])
def test_wrong_session_phase_is_vetoed(gate: RiskGate, minutes: int) -> None:
    ctx = make_context(session=make_session(SESSION_OPEN + timedelta(minutes=minutes)))
    verdict = gate.evaluate(make_intent(), ctx)
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "seans asamasi")


def test_existing_position_in_the_same_symbol_is_vetoed(gate: RiskGate) -> None:
    ctx = make_context(positions={"SPY": other_position("SPY")})
    verdict = gate.evaluate(make_intent(), ctx)
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "zaten acik pozisyon")


def test_concurrent_position_limit(gate: RiskGate) -> None:
    positions = {name: other_position(name) for name in ("AAPL", "MSFT", "NVDA")}
    verdict = gate.evaluate(make_intent(), make_context(positions=positions))
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "es zamanli pozisyon siniri")


# --------------------------------------------------------------------------
# PDT
# --------------------------------------------------------------------------


def test_pdt_limit_blocks_the_fourth_day_trade() -> None:
    """Asilirsa hesap 90 gun kisitlanir; sinir broker'a birakilmaz."""
    gate = RiskGate(RiskSection())
    ctx = make_context(account=make_account(equity=20_000, daytrade_count=3))
    verdict = gate.evaluate(make_intent(), ctx)
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "PDT siniri")


def test_pdt_allows_trades_below_the_limit() -> None:
    gate = RiskGate(RiskSection())
    ctx = make_context(account=make_account(equity=20_000, daytrade_count=2))
    assert gate.evaluate(make_intent(), ctx).allowed


def test_pdt_does_not_apply_above_the_equity_threshold() -> None:
    gate = RiskGate(RiskSection())
    ctx = make_context(account=make_account(equity=30_000, daytrade_count=5))
    assert gate.evaluate(make_intent(), ctx).allowed


def test_pdt_can_be_disabled() -> None:
    gate = RiskGate(RiskSection(enforce_pdt=False))
    ctx = make_context(account=make_account(equity=20_000, daytrade_count=9))
    assert gate.evaluate(make_intent(), ctx).allowed


# --------------------------------------------------------------------------
# Enstruman kalitesi
# --------------------------------------------------------------------------


def test_cheap_instruments_are_vetoed(gate: RiskGate) -> None:
    ctx = make_context(quote=make_quote(mid=3.0))
    verdict = gate.evaluate(make_intent(price=3.0, stop=2.9), ctx)
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "fiyat cok dusuk")


def test_missing_quote_is_vetoed(gate: RiskGate) -> None:
    """Bilinmeyen maliyetle islem acmaktansa islem acmamak tercih edilir."""
    verdict = gate.evaluate(make_intent(), make_context(quote=None))
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "kotasyon yok")


def test_wide_spread_is_vetoed(gate: RiskGate) -> None:
    """'Ufak marj' stratejisini olduren tek maliyet spread'dir."""
    verdict = gate.evaluate(make_intent(), make_context(quote=make_quote(spread_bps=40)))
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "spread cok genis")


def test_crossed_market_is_vetoed(gate: RiskGate) -> None:
    from tlab.core.types import Quote

    crossed = Quote(symbol="SPY", ts=SESSION_OPEN, bid=100.05, ask=100.0)
    verdict = gate.evaluate(make_intent(), make_context(quote=crossed))
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "capraz piyasa")


def test_gate_enforces_its_own_minimum_stop_distance(gate: RiskGate) -> None:
    """Kapi stratejiye guvenmez: kendi tabanini ayrica uygular."""
    verdict = gate.evaluate(make_intent(price=100.0, stop=99.98), make_context())
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "stop mesafesi cok dar")


# --------------------------------------------------------------------------
# Sermaye sinirlari
# --------------------------------------------------------------------------


def test_risk_budget_too_small_for_one_share(gate: RiskGate) -> None:
    ctx = make_context(account=make_account(equity=100.0))
    verdict = gate.evaluate(make_intent(), ctx)
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "bir hisseye yetmiyor")


def test_gross_exposure_cap_reduces_position_size(gate: RiskGate) -> None:
    """Tek islemin riski kucuk olsa da toplam maruziyet tehlikeli olabilir."""
    # Maruziyet tavani 50.000; 45.000 dolu, 5.000 kaldi -> 50 adet
    positions = {"AAPL": other_position("AAPL", qty=450, price=100.0)}
    ctx = make_context(
        positions=positions,
        account=make_account(equity=100_000),
    )
    gate = RiskGate(RiskSection(max_concurrent_positions=5))
    verdict = gate.evaluate(make_intent(), ctx)
    assert verdict.allowed
    assert verdict.qty == 50


def test_full_exposure_is_vetoed() -> None:
    positions = {"AAPL": other_position("AAPL", qty=600, price=100.0)}
    gate = RiskGate(RiskSection(max_concurrent_positions=5))
    verdict = gate.evaluate(make_intent(), make_context(positions=positions))
    assert not verdict.allowed
    assert vetoed_for(verdict.vetoes, "maruziyet siniri dolu")


def test_buying_power_caps_the_position(gate: RiskGate) -> None:
    ctx = make_context(account=make_account(equity=100_000, buying_power=2_000))
    verdict = gate.evaluate(make_intent(), ctx)
    assert verdict.allowed
    assert verdict.qty == 20


def test_gross_exposure_helper() -> None:
    positions = {"A": other_position("A", qty=10, price=50.0), "B": other_position("B", qty=5)}
    assert gross_exposure(positions) == pytest.approx(1_000.0)
    assert gross_exposure({}) == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Sebeplerin toplanmasi
# --------------------------------------------------------------------------


def test_all_veto_reasons_are_collected(gate: RiskGate) -> None:
    """Ilk redde durmak, ogrenme katmanindan bilgi saklamak olurdu.

    'Bu islem neden olmadi' sorusunun cevabi cogu zaman tek sebep
    degil, birkac sebebin birlesimidir.
    """
    ctx: Context = make_context(
        account=make_account(equity=90_000, last_equity=100_000, trading_blocked=True),
        quote=None,
        positions={"SPY": other_position("SPY")},
    )
    verdict = gate.evaluate(make_intent(), ctx)
    assert not verdict.allowed
    assert len(verdict.vetoes) >= 4, verdict.vetoes
    for fragment in ("islem yapmaya kapali", "gunluk zarar", "zaten acik", "kotasyon yok"):
        assert vetoed_for(verdict.vetoes, fragment), fragment
