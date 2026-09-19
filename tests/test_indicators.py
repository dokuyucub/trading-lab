"""Gosterge testleri.

Gostergeler stop mesafesini ve giris kararini belirliyor; yanlis
hesaplanan bir ATR dogrudan yanlis pozisyon boyutu demek. Bu yuzden
degerler elle hesaplanmis beklentilerle karsilastiriliyor, kendi
ciktisiyla degil.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import SESSION_OPEN, make_bars
from tlab.core.types import Bar
from tlab.features.indicators import (
    atr,
    average_volume,
    ema,
    opening_range,
    relative_volume,
    session_vwap,
    true_range,
)

# --------------------------------------------------------------------------
# True Range / ATR
# --------------------------------------------------------------------------


def test_true_range_without_previous_close() -> None:
    bar = Bar(symbol="X", ts=SESSION_OPEN, open=100, high=102, low=99, close=101, volume=1)
    assert true_range(bar, None) == pytest.approx(3.0)


def test_true_range_accounts_for_gaps() -> None:
    """Gap'li acilista ham bar araligi oynakligi oldugundan kucuk gosterir."""
    bar = Bar(symbol="X", ts=SESSION_OPEN, open=105, high=106, low=104, close=105.5, volume=1)
    assert bar.range == pytest.approx(2.0)
    # Onceki kapanis 100 ise gercek hareket 6 birim.
    assert true_range(bar, 100.0) == pytest.approx(6.0)


def test_atr_returns_none_without_enough_history() -> None:
    """Yarim veriyle hesaplanan ATR yanlis stop mesafesi uretir."""
    assert atr(make_bars(10), period=14) is None
    assert atr([], period=14) is None


def test_atr_of_constant_range_series_equals_that_range() -> None:
    bars = make_bars(40, step=0.0, spread=0.5)  # her bar 1,0 birim genis
    value = atr(bars, period=14)
    assert value is not None
    assert value == pytest.approx(1.0, abs=0.01)


def test_atr_grows_with_volatility() -> None:
    calm = atr(make_bars(40, spread=0.2), period=14)
    wild = atr(make_bars(40, spread=2.0), period=14)
    assert calm is not None and wild is not None
    assert wild > calm * 5


# --------------------------------------------------------------------------
# EMA
# --------------------------------------------------------------------------


def test_ema_of_constant_series_is_that_constant() -> None:
    assert ema([5.0] * 30, period=10) == pytest.approx(5.0)


def test_ema_tracks_recent_values_more_closely_than_mean() -> None:
    values = [1.0] * 20 + [10.0] * 5
    result = ema(values, period=10)
    assert result is not None
    assert result > sum(values) / len(values)


def test_ema_needs_enough_points() -> None:
    assert ema([1.0, 2.0], period=10) is None


# --------------------------------------------------------------------------
# VWAP
# --------------------------------------------------------------------------


def test_vwap_is_volume_weighted() -> None:
    """Buyuk hacimli bar ortalamayi kendine ceker."""
    cheap = make_bars(1, base=100.0, spread=0.0, volume=1_000)
    rich = make_bars(
        1, start=SESSION_OPEN + timedelta(minutes=1), base=200.0, spread=0.0, volume=9_000
    )
    value = session_vwap(cheap + rich)
    assert value is not None
    # Agirlikli ortalama: (100*1000 + 200*9000) / 10000 = 190
    assert value == pytest.approx(190.0)


def test_vwap_without_volume_is_undefined() -> None:
    assert session_vwap(make_bars(5, volume=0)) is None
    assert session_vwap([]) is None


# --------------------------------------------------------------------------
# Hacim
# --------------------------------------------------------------------------


def test_average_volume() -> None:
    assert average_volume(make_bars(10, volume=500), lookback=5) == pytest.approx(500)
    assert average_volume(make_bars(3), lookback=5) is None


def test_relative_volume_compares_last_bar_to_baseline() -> None:
    bars = make_bars(25, volume=1_000)
    spike = bars[-1].model_copy(update={"volume": 3_000.0})
    result = relative_volume([*bars[:-1], spike], lookback=20)
    assert result is not None
    assert result == pytest.approx(3.0)


def test_relative_volume_needs_a_baseline() -> None:
    assert relative_volume(make_bars(5), lookback=20) is None
    assert relative_volume(make_bars(25, volume=0), lookback=20) is None


# --------------------------------------------------------------------------
# Acilis araligi
# --------------------------------------------------------------------------


def test_opening_range_spans_only_the_window() -> None:
    """Pencere disindaki barlar araligi genisletmemeli."""
    inside = make_bars(15, base=100.0, spread=0.5)
    outside = make_bars(10, start=SESSION_OPEN + timedelta(minutes=15), base=120.0, spread=0.5)
    levels = opening_range(inside + outside, SESSION_OPEN, minutes=15)
    assert levels is not None
    high, low = levels
    assert high == pytest.approx(100.5)
    assert low == pytest.approx(99.5)


def test_incomplete_opening_range_is_not_reported() -> None:
    """Yarim aralikla islem acmak, olusmamis bir seviyeyi kirmis saymaktir."""
    assert opening_range(make_bars(8), SESSION_OPEN, minutes=15) is None


def test_opening_range_completes_exactly_at_the_boundary() -> None:
    # 15 bar = 14:30..14:44, sonuncusunun zamani 14:44 < 14:45 -> tamamlanmadi
    assert opening_range(make_bars(15), SESSION_OPEN, minutes=15) is None
    # 16. bar 14:45'te acilir, yani pencere kapandi
    assert opening_range(make_bars(16), SESSION_OPEN, minutes=15) is not None


def test_opening_range_ignores_previous_session() -> None:
    """Onceki gunun barlari bugunun araligina karismamali."""
    yesterday = make_bars(30, start=SESSION_OPEN - timedelta(days=1), base=50.0)
    today = make_bars(20, start=SESSION_OPEN, base=100.0, spread=0.5)
    levels = opening_range(yesterday + today, SESSION_OPEN, minutes=15)
    assert levels is not None
    assert levels[1] == pytest.approx(99.5)


def test_opening_range_without_bars() -> None:
    assert opening_range([], SESSION_OPEN, minutes=15) is None
