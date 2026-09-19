"""Seans durumu testleri.

Seans asamasi, sistemin ne zaman islem acacagini ve ne zaman
pozisyon kapatacagini belirliyor. Yanlis hesaplanmis bir saat,
kapanistan sonra pozisyon acmak ya da zorunlu kapanisi kacirmak
demek.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tlab.features.context import SessionPhase, build_session_state

KWARGS = {
    "exchange_timezone": "America/New_York",
    "regular_open": "09:30",
    "regular_close": "16:00",
    "flatten_before_close_minutes": 10,
    "opening_range_minutes": 15,
}

# 2026-01-05 kis saati: New York UTC-5, yani acilis 14:30 UTC.
WINTER_OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("minutes_from_open", "expected"),
    [
        (-60, SessionPhase.PRE_OPEN),
        (-1, SessionPhase.PRE_OPEN),
        (0, SessionPhase.OPENING_RANGE),
        (14, SessionPhase.OPENING_RANGE),
        (15, SessionPhase.REGULAR),
        (300, SessionPhase.REGULAR),
        (380, SessionPhase.FLATTEN),  # 16:00'a 10 dk kala
        (390, SessionPhase.CLOSED),
        (500, SessionPhase.CLOSED),
    ],
)
def test_phase_boundaries(minutes_from_open: int, expected: SessionPhase) -> None:
    state = build_session_state(WINTER_OPEN + timedelta(minutes=minutes_from_open), **KWARGS)  # type: ignore[arg-type]
    assert state.phase is expected


def test_only_regular_phase_opens_positions() -> None:
    for minutes, can_open in [(-10, False), (5, False), (60, True), (385, False), (400, False)]:
        state = build_session_state(WINTER_OPEN + timedelta(minutes=minutes), **KWARGS)  # type: ignore[arg-type]
        assert state.can_open_new_positions is can_open


def test_flatten_window_is_flagged() -> None:
    state = build_session_state(WINTER_OPEN + timedelta(minutes=385), **KWARGS)  # type: ignore[arg-type]
    assert state.must_flatten
    assert not state.can_open_new_positions


def test_minute_counters() -> None:
    state = build_session_state(WINTER_OPEN + timedelta(minutes=90), **KWARGS)  # type: ignore[arg-type]
    assert state.minutes_since_open == pytest.approx(90)
    assert state.minutes_to_close == pytest.approx(300)


def test_daylight_saving_is_handled_by_the_timezone_database() -> None:
    """Sabit saat farki varsaymak yilda iki kez bir saatlik kaymaya yol acar.

    ABD yaz saatine Mart'ta gecer; ayni yerel acilis saati UTC'de
    farkli saatlere denk gelir.
    """
    winter = build_session_state(datetime(2026, 1, 15, 18, 0, tzinfo=UTC), **KWARGS)  # type: ignore[arg-type]
    summer = build_session_state(datetime(2026, 7, 15, 18, 0, tzinfo=UTC), **KWARGS)  # type: ignore[arg-type]

    assert winter.session_open.hour == 14  # EST: UTC-5
    assert summer.session_open.hour == 13  # EDT: UTC-4
    assert winter.session_close.hour == 21
    assert summer.session_close.hour == 20


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        build_session_state(datetime(2026, 1, 5, 14, 30), **KWARGS)  # type: ignore[arg-type]


def test_flatten_and_opening_range_anchors() -> None:
    state = build_session_state(WINTER_OPEN + timedelta(minutes=60), **KWARGS)  # type: ignore[arg-type]
    assert state.opening_range_end == state.session_open + timedelta(minutes=15)
    assert state.flatten_at == state.session_close - timedelta(minutes=10)
