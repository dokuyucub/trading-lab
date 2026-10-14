"""Golge gozlem kapisi (docs/designs/shadow-observation.md §5).

Gosterilenler: acilis saat dilimi kuralindan gelir (yaz/kis saati);
erken, pencere ici ve gec kararlari; gunluk teklik yalnizca kayit
yazmis kosulari sayar; plan disi gun hicbir sey yapmaz.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tlab.shadow.schedule import (
    GATE_LATE,
    GATE_OBSERVE,
    GATE_SKIP,
    PriorRun,
    decide,
    regular_open,
    session_day_of,
)

WINTER = date(2026, 1, 5)
SUMMER = date(2026, 7, 6)
PLANNED = (WINTER, SUMMER)


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (WINTER, at(WINTER, 14, 30)),  # EST, UTC-5
        (SUMMER, at(SUMMER, 13, 30)),  # EDT, UTC-4
        (date(2026, 3, 9), at(date(2026, 3, 9), 13, 30)),  # gecisten sonraki ilk pazartesi
        (date(2026, 11, 2), at(date(2026, 11, 2), 14, 30)),  # kis saatine donus sonrasi
    ],
)
def test_the_open_follows_the_time_zone_rule(day: date, expected: datetime) -> None:
    assert regular_open(day) == expected


@pytest.mark.parametrize(
    ("now", "action", "reason"),
    [
        (at(WINTER, 13, 29), GATE_SKIP, "erken"),
        (at(WINTER, 13, 30), GATE_OBSERVE, "baslangic penceresi icinde"),
        (at(WINTER, 14, 29), GATE_OBSERVE, "baslangic penceresi icinde"),
        (at(WINTER, 14, 29) + timedelta(seconds=1), GATE_LATE, "gec baslangic"),
        (at(WINTER, 14, 50), GATE_LATE, "gec baslangic"),
    ],
)
def test_early_in_window_and_late(now: datetime, action: str, reason: str) -> None:
    decision = decide(now, PLANNED, [])
    assert (decision.action, decision.reason, decision.session_day) == (action, reason, WINTER)


def test_two_crons_cover_both_seasons() -> None:
    """Iki UTC satiri: 12:50Z ve 13:50Z.

    Kis: 12:50Z erken, 13:50Z pencerede. Yaz: 12:50Z pencerede, 13:50Z
    gec ve gercek kosudan sonra bos gecer.
    """
    assert decide(at(WINTER, 12, 50), PLANNED, []).action == GATE_SKIP
    assert decide(at(WINTER, 13, 50), PLANNED, []).action == GATE_OBSERVE
    assert decide(at(SUMMER, 12, 50), PLANNED, []).action == GATE_OBSERVE
    observed = [PriorRun(SUMMER, recorded=True)]
    assert decide(at(SUMMER, 13, 50), PLANNED, observed).action == GATE_SKIP


def test_a_late_cron_records_the_day_only_if_nothing_else_did() -> None:
    late = at(SUMMER, 13, 50)
    assert decide(late, PLANNED, []).action == GATE_LATE
    assert decide(late, PLANNED, [PriorRun(SUMMER, recorded=True)]).action == GATE_SKIP


def test_only_runs_that_recorded_count_for_uniqueness() -> None:
    """Bos gecen kosu (kayit isi atlanmis) gercek kosuyu engellemez."""
    window = at(WINTER, 13, 50)
    skipped = [PriorRun(WINTER, recorded=False)]
    assert decide(window, PLANNED, skipped).action == GATE_OBSERVE


def test_a_second_run_the_same_day_is_refused() -> None:
    window = at(WINTER, 13, 55)
    decision = decide(window, PLANNED, [PriorRun(WINTER, recorded=True)])
    assert (decision.action, decision.reason) == (GATE_SKIP, "gun zaten kaydedildi")


def test_another_days_run_does_not_block_today() -> None:
    window = at(SUMMER, 12, 50)
    assert decide(window, PLANNED, [PriorRun(WINTER, recorded=True)]).action == GATE_OBSERVE


@pytest.mark.parametrize(
    "now",
    [at(date(2026, 1, 6), 13, 50), at(date(2026, 1, 10), 13, 50), at(date(2026, 12, 1), 13, 50)],
    ids=["unplanned-weekday", "weekend", "after-the-last-planned-day"],
)
def test_an_unplanned_day_does_nothing(now: datetime) -> None:
    decision = decide(now, PLANNED, [])
    assert (decision.action, decision.reason) == (GATE_SKIP, "plan disi gun")


def test_the_session_day_is_the_new_york_date() -> None:
    """UTC gece yarisindan sonra New York hala onceki gundedir."""
    assert session_day_of(datetime(2026, 1, 6, 3, 0, tzinfo=UTC)) == WINTER
    with pytest.raises(ValueError, match="timezone"):
        session_day_of(datetime(2026, 1, 5, 13, 50))
