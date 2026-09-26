"""Validated inputs for versioned research selection; no I/O or snapshot hashing.

The v1 payload remains unchanged inside a separate local receipt envelope.
Missing receipt evidence is never inferred from the provider's timestamps.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from tlab.core.research import EventKind, Evidence, KnowledgeProvenance, ResearchEvent


class ReceivedResearchEvent(Evidence):
    """One immutable local receipt of a revision, not a provider timestamp.

    Ingestion must supply authentic receipt evidence. Validation checks temporal
    consistency, not the truth of the supplied clock or provenance label.
    """

    schema_version: Literal[2] = 2
    event: ResearchEvent
    received_at: AwareDatetime

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.event.known_at > self.received_at:
            raise ValueError("received_at cannot precede known_at")
        return self


class ResearchQuery(Evidence):
    """Explicit as-of request; dataset identity belongs to the evaluation manifest.

    Policy identity is required rather than silently inherited. Collection fields
    are canonical sets serialized as sorted tuples for stable downstream hashes.
    This input does not select revisions or establish complete coverage.
    """

    schema_version: Literal[2] = 2
    source: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    kinds: tuple[EventKind, ...]
    coverage_start: AwareDatetime
    coverage_end: AwareDatetime
    as_of: AwareDatetime
    policy_version: str = Field(min_length=1)
    allowed_provenance: tuple[KnowledgeProvenance, ...] = (KnowledgeProvenance.OBSERVED,)

    @field_validator("kinds")
    @classmethod
    def canonical_kinds(cls, value: tuple[EventKind, ...]) -> tuple[EventKind, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("query kinds must be nonempty and unique")
        return tuple(sorted(value))

    @field_validator("allowed_provenance")
    @classmethod
    def canonical_provenance(
        cls, value: tuple[KnowledgeProvenance, ...]
    ) -> tuple[KnowledgeProvenance, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("allowed provenance must be nonempty and unique")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.coverage_start >= self.coverage_end:
            raise ValueError("coverage interval must be nonempty [start, end)")
        return self

    def allows_knowledge(self, receipt: ReceivedResearchEvent) -> bool:
        """Time/provenance gate ONLY, not scope matching or revision selection.

        A wider provenance filter never removes the local time gate. Scope is
        deliberately not applied here: first select the latest visible revision,
        then apply scope, so a moved/cancelled event cannot revive an old revision.
        This predicate is not sufficient for snapshot or promotion eligibility.
        """
        return (
            receipt.event.known_at <= receipt.received_at <= self.as_of
            and receipt.event.knowledge_provenance in self.allowed_provenance
        )
