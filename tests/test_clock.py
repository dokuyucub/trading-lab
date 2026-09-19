"""Zaman soyutlamasi testleri."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from tlab.core.clock import Clock, LiveClock, SimClock


def test_live_clock_utc_aware() -> None:
    now = LiveClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_both_clocks_satisfy_protocol() -> None:
    assert isinstance(LiveClock(), Clock)
    assert isinstance(SimClock(datetime(2026, 1, 1, tzinfo=UTC)), Clock)


def test_sim_clock_advances() -> None:
    clock = SimClock(datetime(2026, 1, 1, tzinfo=UTC))
    clock.set(datetime(2026, 1, 2, tzinfo=UTC))
    assert clock.now() == datetime(2026, 1, 2, tzinfo=UTC)


def test_sim_clock_rejects_going_backwards() -> None:
    """Zamanin geri akmasi backtest'te sessiz veri sizintisi demektir."""
    clock = SimClock(datetime(2026, 1, 2, tzinfo=UTC))
    with pytest.raises(ValueError, match="geriye alinamaz"):
        clock.set(datetime(2026, 1, 1, tzinfo=UTC))


def test_sim_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="Timezone bilgisi olmayan"):
        SimClock(datetime(2026, 1, 1))


def test_sim_clock_normalizes_to_utc() -> None:
    """Farkli dilimde verilen zaman UTC'ye cevrilerek saklanir."""
    eastern = timezone(timedelta(hours=-5))
    clock = SimClock(datetime(2026, 1, 1, 9, 30, tzinfo=eastern))
    assert clock.now() == datetime(2026, 1, 1, 14, 30, tzinfo=UTC)
