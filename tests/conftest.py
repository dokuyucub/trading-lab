"""Ortak test yardimcilari.

Testlerin hicbiri AG ERISIMI gerektirmez. Alpaca'ya baglanan kod
yollari ayri tutuldugu icin cekirdek mantik tamamen cevrimdisi
dogrulanabilir - bu, tasarimin dogru katmanlandiginin de gostergesi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tlab.config import RiskSection
from tlab.core.types import Account, Bar, Intent, Position, Quote, Side
from tlab.features.context import Context, SessionState, build_session_state

BASE_YAML = """
app:
  exchange_timezone: America/New_York
data:
  feed: iex
  cache_dir: data/bars
  default_timeframe: 1Min
session:
  regular_open: "09:30"
  regular_close: "16:00"
  flatten_before_close_minutes: 10
  allow_extended_hours: false
risk:
  max_risk_per_trade_pct: 0.5
  max_daily_loss_pct: 2.0
  max_concurrent_positions: 3
  max_gross_exposure_pct: 50.0
  min_price: 5.0
  max_spread_bps: 15
  enforce_pdt: true
  pdt_equity_threshold: 25000
  max_day_trades_per_window: 3
journal:
  path: data/journal.db
"""

UNIVERSE_YAML = """
symbols:
  - SPY
  - AAPL
"""


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Gecerli config dosyalari iceren gecici bir proje koku."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "base.yaml").write_text(BASE_YAML, encoding="utf-8")
    (config_dir / "universe.yaml").write_text(UNIVERSE_YAML, encoding="utf-8")
    return tmp_path


@pytest.fixture
def sample_bars() -> list[Bar]:
    """Yukselen egilimli 10 dakikalik bar serisi."""
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    return [
        Bar(
            symbol="SPY",
            ts=start + timedelta(minutes=i),
            open=100.0 + i * 0.1,
            high=100.5 + i * 0.1,
            low=99.8 + i * 0.1,
            close=100.3 + i * 0.1,
            volume=10_000 + i * 100,
            vwap=100.2 + i * 0.1,
            trade_count=50 + i,
        )
        for i in range(10)
    ]


@pytest.fixture
def sample_intent() -> Intent:
    return Intent(
        strategy_id="orb",
        params_version="v0",
        symbol="SPY",
        side=Side.BUY,
        reference_price=100.0,
        stop_loss=99.0,
        take_profit=101.5,
        confidence=0.6,
        reason="acilis araligi kirilimi",
        features={"atr": 0.8, "rvol": 1.9},
    )


# --------------------------------------------------------------------------
# Faz 1 yardimcilari
# --------------------------------------------------------------------------

SESSION_OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
"""2026-01-05 09:30 New York (kis saati, UTC-5)."""


def make_session(
    now: datetime | None = None,
    *,
    opening_range_minutes: int = 15,
    flatten_before_close_minutes: int = 10,
) -> SessionState:
    """Test icin seans durumu uretir (varsayilan: acilistan 30 dk sonra)."""
    return build_session_state(
        now or SESSION_OPEN + timedelta(minutes=30),
        exchange_timezone="America/New_York",
        regular_open=(9, 30),
        regular_close=(16, 0),
        flatten_before_close_minutes=flatten_before_close_minutes,
        opening_range_minutes=opening_range_minutes,
    )


def make_bars(
    count: int,
    *,
    start: datetime | None = None,
    symbol: str = "SPY",
    base: float = 100.0,
    step: float = 0.0,
    spread: float = 0.4,
    volume: float = 10_000,
) -> list[Bar]:
    """Duzenli bir bar serisi uretir.

    `step` her barda kapanisa eklenen miktar: 0 yatay, pozitif
    yukselen, negatif dusen seri verir.
    """
    start = start or SESSION_OPEN
    bars: list[Bar] = []
    for index in range(count):
        close = base + step * index
        bars.append(
            Bar(
                symbol=symbol,
                ts=start + timedelta(minutes=index),
                open=close - step / 2 if step else close,
                high=close + spread,
                low=close - spread,
                close=close,
                volume=volume,
                vwap=close,
                trade_count=50,
            )
        )
    return bars


def make_account(
    equity: float = 100_000.0,
    *,
    last_equity: float | None = None,
    buying_power: float | None = None,
    daytrade_count: int = 0,
    trading_blocked: bool = False,
) -> Account:
    return Account(
        equity=equity,
        last_equity=equity if last_equity is None else last_equity,
        cash=equity,
        buying_power=equity * 2 if buying_power is None else buying_power,
        daytrade_count=daytrade_count,
        trading_blocked=trading_blocked,
    )


def make_quote(symbol: str = "SPY", *, mid: float = 100.0, spread_bps: float = 2.0) -> Quote:
    half = mid * spread_bps / 10_000 / 2
    return Quote(
        symbol=symbol,
        ts=SESSION_OPEN + timedelta(minutes=30),
        bid=mid - half,
        ask=mid + half,
        bid_size=100,
        ask_size=100,
    )


class _Default:
    """'Verilmedi' ile 'bilincli olarak None' arasindaki farki tasir.

    Kotasyonun olmamasi test edilmesi gereken gercek bir durum
    (risk kapisi o zaman veto ediyor). None'i varsayilan olarak
    kullanan bir yardimci bu durumu ifade edemezdi.
    """


DEFAULT = _Default()


def make_context(
    *,
    symbol: str = "SPY",
    bars: list[Bar] | None = None,
    session: SessionState | None = None,
    account: Account | None = None,
    positions: dict[str, Position] | None = None,
    quote: Quote | _Default | None = DEFAULT,
) -> Context:
    resolved = make_quote(symbol) if isinstance(quote, _Default) else quote
    return Context(
        symbol=symbol,
        session=session or make_session(),
        bars=tuple(bars if bars is not None else make_bars(40)),
        account=account or make_account(),
        positions=positions or {},
        quote=resolved,
    )


@pytest.fixture
def risk_config() -> RiskSection:
    """Varsayilan risk ayarlari."""
    return RiskSection()
