"""Bar onbellegi testleri."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tlab.core.types import Bar, Timeframe
from tlab.data.cache import BarCache
from tlab.errors import DataError


@pytest.fixture
def cache(tmp_path: Path) -> BarCache:
    return BarCache(tmp_path / "bars")


def test_missing_cache_returns_empty(cache: BarCache) -> None:
    assert cache.load("SPY", Timeframe.M1) == []
    assert cache.coverage("SPY", Timeframe.M1) is None


def test_round_trip_preserves_values(cache: BarCache, sample_bars: list[Bar]) -> None:
    assert cache.save("SPY", Timeframe.M1, sample_bars) == 10
    loaded = cache.load("SPY", Timeframe.M1)
    assert len(loaded) == 10
    assert loaded[0].ts == sample_bars[0].ts
    assert loaded[0].close == pytest.approx(sample_bars[0].close)
    assert loaded[0].vwap == pytest.approx(sample_bars[0].vwap)
    assert loaded[0].trade_count == sample_bars[0].trade_count


def test_timestamps_stay_utc_aware(cache: BarCache, sample_bars: list[Bar]) -> None:
    cache.save("SPY", Timeframe.M1, sample_bars)
    loaded = cache.load("SPY", Timeframe.M1)
    assert all(bar.ts.tzinfo is not None for bar in loaded)
    assert all(bar.ts.utcoffset() == timedelta(0) for bar in loaded)


def test_rewriting_same_bars_does_not_duplicate(cache: BarCache, sample_bars: list[Bar]) -> None:
    cache.save("SPY", Timeframe.M1, sample_bars)
    assert cache.save("SPY", Timeframe.M1, sample_bars) == 10


def test_newer_bar_overwrites_same_timestamp(cache: BarCache, sample_bars: list[Bar]) -> None:
    """Alpaca gecmis barlari duzeltebiliyor; son gelen dogru kabul edilir."""
    cache.save("SPY", Timeframe.M1, sample_bars)
    corrected = sample_bars[0].model_copy(update={"close": 999.0, "high": 1000.0})
    cache.save("SPY", Timeframe.M1, [corrected])
    assert cache.load("SPY", Timeframe.M1)[0].close == pytest.approx(999.0)


def test_merge_keeps_chronological_order(cache: BarCache, sample_bars: list[Bar]) -> None:
    cache.save("SPY", Timeframe.M1, sample_bars[5:])
    cache.save("SPY", Timeframe.M1, sample_bars[:5])
    loaded = cache.load("SPY", Timeframe.M1)
    assert [bar.ts for bar in loaded] == sorted(bar.ts for bar in loaded)


def test_date_range_filtering(cache: BarCache, sample_bars: list[Bar]) -> None:
    cache.save("SPY", Timeframe.M1, sample_bars)
    subset = cache.load("SPY", Timeframe.M1, start=sample_bars[3].ts, end=sample_bars[6].ts)
    assert len(subset) == 4
    assert subset[0].ts == sample_bars[3].ts


def test_coverage_reports_span(cache: BarCache, sample_bars: list[Bar]) -> None:
    cache.save("SPY", Timeframe.M1, sample_bars)
    span = cache.coverage("SPY", Timeframe.M1)
    assert span == (sample_bars[0].ts, sample_bars[-1].ts)


def test_timeframes_are_stored_separately(cache: BarCache, sample_bars: list[Bar]) -> None:
    cache.save("SPY", Timeframe.M1, sample_bars)
    assert cache.load("SPY", Timeframe.M5) == []


def test_wrong_symbol_is_rejected(cache: BarCache, sample_bars: list[Bar]) -> None:
    """Yanlis sembole yazilan veri, sessizce bozuk backtest uretir."""
    foreign = sample_bars[0].model_copy(update={"symbol": "AAPL"})
    with pytest.raises(DataError, match="baska sembol"):
        cache.save("SPY", Timeframe.M1, [foreign])


def test_saving_nothing_is_harmless(cache: BarCache) -> None:
    assert cache.save("SPY", Timeframe.M1, []) == 0


def test_no_partial_file_left_behind(cache: BarCache, sample_bars: list[Bar]) -> None:
    """Yazma atomik: yarim .tmp dosyasi kalmamali."""
    cache.save("SPY", Timeframe.M1, sample_bars)
    assert list(cache.path_for("SPY", Timeframe.M1).parent.glob("*.tmp")) == []


def test_optional_fields_survive_as_none(cache: BarCache) -> None:
    bar = Bar(
        symbol="SPY",
        ts=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
        open=100,
        high=101,
        low=99,
        close=100,
        volume=10,
    )
    cache.save("SPY", Timeframe.D1, [bar])
    loaded = cache.load("SPY", Timeframe.D1)[0]
    assert loaded.vwap is None
    assert loaded.trade_count is None
