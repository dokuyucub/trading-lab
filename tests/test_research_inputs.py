"""Temporal boundaries that must survive exploration and historical backfill."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from tlab.core.research import EventKind, KnowledgeProvenance, ResearchEvent
from tlab.core.research_inputs import ReceivedResearchEvent, ResearchQuery

T = datetime(2026, 1, 20, 15, tzinfo=UTC)


def event(**changes: Any) -> ResearchEvent:
    values: dict[str, Any] = {
        "source": "fixture",
        "event_id": "earnings-1",
        "revision": "r1",
        "symbol": "SPY",
        "kind": EventKind.EARNINGS,
        "event_start": T + timedelta(days=1),
        "event_end": T + timedelta(days=1, hours=1),
        "known_at": T - timedelta(days=1),
        "knowledge_provenance": KnowledgeProvenance.OBSERVED,
    }
    return ResearchEvent.model_validate(values | changes)


def query(**changes: Any) -> ResearchQuery:
    values: dict[str, Any] = {
        "source": "fixture",
        "symbol": "SPY",
        "kinds": (EventKind.EARNINGS,),
        "coverage_start": T,
        "coverage_end": T + timedelta(days=2),
        "as_of": T,
        "policy_version": "as-of-v2",
    }
    return ResearchQuery.model_validate(values | changes)


def test_receipt_time_is_required_and_cannot_be_backdated() -> None:
    with pytest.raises(ValidationError, match="received_at"):
        ReceivedResearchEvent.model_validate({"event": event().model_dump()})
    with pytest.raises(ValidationError, match="precede known_at"):
        ReceivedResearchEvent(event=event(), received_at=T - timedelta(days=2))


@pytest.mark.parametrize("wide", [False, True])
def test_late_backfill_never_becomes_visible_by_widening_provenance(wide: bool) -> None:
    receipt = ReceivedResearchEvent(
        event=event(knowledge_provenance=KnowledgeProvenance.BACKFILLED),
        received_at=T + timedelta(days=30),
    )
    request = query(allowed_provenance=tuple(KnowledgeProvenance)) if wide else query()
    assert not request.allows_knowledge(receipt)


def test_previously_received_backfill_requires_explicit_filter() -> None:
    receipt = ReceivedResearchEvent(
        event=event(knowledge_provenance=KnowledgeProvenance.BACKFILLED), received_at=T
    )
    assert not query().allows_knowledge(receipt)
    assert query(allowed_provenance=tuple(KnowledgeProvenance)).allows_knowledge(receipt)


def test_receipt_boundary_is_inclusive_but_next_microsecond_is_hidden() -> None:
    assert query().allows_knowledge(ReceivedResearchEvent(event=event(), received_at=T))
    assert not query().allows_knowledge(
        ReceivedResearchEvent(event=event(), received_at=T + timedelta(microseconds=1))
    )


def test_knowledge_gate_does_not_preempt_revision_selection_with_scope_filtering() -> None:
    moved = event(
        symbol="QQQ", event_start=T + timedelta(days=10), event_end=T + timedelta(days=11)
    )
    assert query().allows_knowledge(ReceivedResearchEvent(event=moved, received_at=T))
    cancelled = event(cancelled=True)
    assert query().allows_knowledge(ReceivedResearchEvent(event=cancelled, received_at=T))


@pytest.mark.parametrize(
    "changes",
    [
        {"kinds": ()},
        {"kinds": (EventKind.NEWS, EventKind.NEWS)},
        {"allowed_provenance": ()},
        {"allowed_provenance": (KnowledgeProvenance.OBSERVED,) * 2},
        {"coverage_end": T},
        {"as_of": T.replace(tzinfo=None)},
        {"source": " "},
        {"policy_version": " "},
        {"unexpected": True},
        {"schema_version": 1},
    ],
)
def test_invalid_or_ambiguous_queries_are_rejected(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        query(**changes)


def test_receipt_rejects_naive_time_and_preserves_v1_payload() -> None:
    original = event()
    with pytest.raises(ValidationError):
        ReceivedResearchEvent(event=original, received_at=T.replace(tzinfo=None))
    receipt = ReceivedResearchEvent(event=original, received_at=T)
    loaded = ReceivedResearchEvent.model_validate_json(receipt.model_dump_json())
    assert loaded == receipt
    assert loaded.event.model_dump_json() == original.model_dump_json()
    with pytest.raises(ValidationError, match="frozen"):
        receipt.received_at = T + timedelta(days=1)


def test_query_order_and_equivalent_offsets_have_canonical_serialization() -> None:
    first = query(kinds=(EventKind.NEWS, EventKind.EARNINGS))
    second = query(kinds=(EventKind.EARNINGS, EventKind.NEWS), as_of="2026-01-20T10:00:00-05:00")
    assert first.model_dump_json() == second.model_dump_json()
    assert ResearchQuery.model_validate_json(first.model_dump_json()) == first
    assert query().allowed_provenance == (KnowledgeProvenance.OBSERVED,)
