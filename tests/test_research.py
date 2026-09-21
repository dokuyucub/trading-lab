"""Research evidence must not invent historical knowledge or absence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from conftest import make_context
from tlab.core.research import (
    EventKind,
    EventPrecision,
    KnowledgeProvenance,
    ResearchEvent,
    ResearchSnapshot,
    ResearchStatus,
)

NOW = datetime(2026, 9, 21, 14, tzinfo=UTC)


def event(**changes: Any) -> ResearchEvent:
    fields: dict[str, Any] = {
        "source": "fixture",
        "event_id": "earnings-1",
        "revision": "1",
        "symbol": "SPY",
        "kind": EventKind.EARNINGS,
        "event_start": NOW + timedelta(hours=1),
        "event_end": NOW + timedelta(hours=2),
        "published_at": NOW - timedelta(hours=2),
        "known_at": NOW - timedelta(hours=1),
        "knowledge_provenance": KnowledgeProvenance.OBSERVED,
    }
    return ResearchEvent(**(fields | changes))


def snapshot(**changes: Any) -> ResearchSnapshot:
    fields: dict[str, Any] = {
        "symbol": "SPY",
        "source": "fixture",
        "kinds": (EventKind.EARNINGS,),
        "coverage_start": NOW - timedelta(days=1),
        "coverage_end": NOW + timedelta(days=1),
        "as_of": NOW,
        "observed_at": NOW,
        "fresh_until": NOW + timedelta(minutes=15),
        "knowledge_provenance": KnowledgeProvenance.OBSERVED,
        "status": ResearchStatus.AVAILABLE,
        "events": (event(),),
    }
    return ResearchSnapshot(**(fields | changes))


def test_hash_is_order_independent_and_roundtrips() -> None:
    events = (event(), event(event_id="earnings-2"))
    original = snapshot(events=events)
    assert original.snapshot_id == snapshot(events=tuple(reversed(events))).snapshot_id
    restored = ResearchSnapshot.model_validate_json(original.model_dump_json())
    assert restored.snapshot_id == original.snapshot_id
    assert snapshot(as_of=NOW + timedelta(seconds=1)).snapshot_id != snapshot().snapshot_id
    assert snapshot(events=(event(revision="2"),)).snapshot_id != snapshot().snapshot_id
    shifted = NOW.astimezone(ZoneInfo("America/New_York"))
    assert snapshot(as_of=shifted).snapshot_id == snapshot().snapshot_id


def test_status_and_provenance_survive_serialization() -> None:
    empty = snapshot(status=ResearchStatus.EMPTY, events=())
    unavailable = snapshot(status=ResearchStatus.UNAVAILABLE, events=())
    assert empty.snapshot_id != unavailable.snapshot_id
    assert empty.has_verified_knowledge
    assert not unavailable.has_verified_knowledge
    for provenance in (KnowledgeProvenance.BACKFILLED, KnowledgeProvenance.PROVIDER_CLAIMED):
        assert not snapshot(knowledge_provenance=provenance).has_verified_knowledge
        assert not snapshot(events=(event(knowledge_provenance=provenance),)).has_verified_knowledge


@pytest.mark.parametrize(
    "changes",
    [
        {"as_of": NOW - timedelta(seconds=1)},
        {"fresh_until": NOW},
        {"fresh_until": NOW - timedelta(seconds=1)},
        {"coverage_end": NOW - timedelta(days=1)},
        {"kinds": ()},
        {"kinds": (EventKind.EARNINGS, EventKind.EARNINGS)},
        {"status": ResearchStatus.AVAILABLE, "events": ()},
        {"status": ResearchStatus.EMPTY},
        {"status": ResearchStatus.UNAVAILABLE},
        {"status": ResearchStatus.STALE},
        {"as_of": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_snapshot_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        snapshot(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"known_at": NOW + timedelta(seconds=1)},
        {"symbol": "QQQ"},
        {"source": "other"},
        {"kind": EventKind.NEWS},
        {"event_start": NOW + timedelta(days=1), "event_end": NOW + timedelta(days=2)},
    ],
)
def test_future_or_out_of_scope_evidence_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        snapshot(events=(event(**changes),))


def test_revision_and_immutability_guards() -> None:
    with pytest.raises(ValidationError):
        snapshot(events=(event(), event(revision="2")))
    value = snapshot()
    with pytest.raises(ValidationError):
        value.status = ResearchStatus.EMPTY
    with pytest.raises(ValidationError):
        value.events[0].revision = "changed"
    stale = snapshot(status=ResearchStatus.STALE, as_of=NOW + timedelta(hours=1))
    assert not stale.has_verified_knowledge


def test_day_precision_covers_dst_day_without_inventing_an_announcement_time() -> None:
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, tzinfo=zone)
    end = datetime(2026, 11, 2, tzinfo=zone)
    value = event(event_start=start, event_end=end, precision=EventPrecision.DAY)
    assert value.event_end.astimezone(UTC) - value.event_start.astimezone(UTC) == timedelta(
        hours=25
    )
    with pytest.raises(ValidationError):
        event(event_start=start, event_end=end - timedelta(hours=1), precision=EventPrecision.DAY)
    with pytest.raises(ValidationError):
        event(event_end=NOW)
    with pytest.raises(ValidationError):
        event(published_at=NOW + timedelta(days=1))


def test_context_requires_same_symbol_and_decision_time() -> None:
    ctx = make_context()
    assert ctx.research is None
    ctx = replace(ctx, session=replace(ctx.session, now=NOW), research=snapshot())
    assert ctx.research is not None and ctx.research.has_verified_knowledge
    with pytest.raises(ValueError):
        replace(ctx, symbol="QQQ")
    with pytest.raises(ValueError):
        replace(ctx, session=replace(ctx.session, now=NOW + timedelta(seconds=1)))


def test_invalid_timezone_is_validation_error() -> None:
    with pytest.raises(ValidationError):
        event(event_timezone="No/Such_Zone")


def test_dst_fold_orders_instants_not_wall_clock_labels() -> None:
    zone = ZoneInfo("America/New_York")
    start = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    end = datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=1)
    value = event(event_start=start, event_end=end)
    assert value.event_end - value.event_start == timedelta(minutes=45)
