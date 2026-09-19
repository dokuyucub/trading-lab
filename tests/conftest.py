"""Ortak test yardimcilari.

Testlerin hicbiri AG ERISIMI gerektirmez. Alpaca'ya baglanan kod
yollari ayri tutuldugu icin cekirdek mantik tamamen cevrimdisi
dogrulanabilir - bu, tasarimin dogru katmanlandiginin de gostergesi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tlab.core.types import Bar, Intent, Side

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
