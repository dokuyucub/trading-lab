"""Immutable research evidence shared by paper, backtest and offline learning.

No provider I/O, wall clock or trading policy belongs here. Snapshot construction
rejects evidence unavailable at the supplied decision time; historical revision
selection and persistence are separate responsibilities.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class ResearchStatus(StrEnum):
    AVAILABLE = "available"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


class KnowledgeProvenance(StrEnum):
    OBSERVED = "observed"
    PROVIDER_CLAIMED = "provider_claimed"
    BACKFILLED = "backfilled"


class EventKind(StrEnum):
    EARNINGS = "earnings"
    NEWS = "news"


class EventPrecision(StrEnum):
    INTERVAL = "interval"
    DAY = "day"


class SessionHint(StrEnum):
    BMO = "bmo"
    AMC = "amc"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    @field_validator("*")
    @classmethod
    def normalize_time(cls, value: Any) -> Any:
        return value.astimezone(UTC) if isinstance(value, datetime) else value


class ResearchEvent(Evidence):
    source: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    kind: EventKind
    event_start: AwareDatetime
    event_end: AwareDatetime
    precision: EventPrecision = EventPrecision.INTERVAL
    event_timezone: str = "America/New_York"
    session_hint: SessionHint = SessionHint.UNKNOWN
    published_at: AwareDatetime | None = None
    known_at: AwareDatetime
    knowledge_provenance: KnowledgeProvenance
    cancelled: bool = False

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        try:
            zone = ZoneInfo(self.event_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown event timezone") from exc
        if self.event_start >= self.event_end:
            raise ValueError("event interval must be nonempty [start, end)")
        if self.published_at is not None and self.published_at > self.known_at:
            raise ValueError("published_at cannot follow known_at")
        if self.precision is EventPrecision.DAY:
            start, end = self.event_start.astimezone(zone), self.event_end.astimezone(zone)
            if (
                start.time() != datetime.min.time()
                or end.time() != datetime.min.time()
                or end.date() != start.date() + timedelta(days=1)
            ):
                raise ValueError("day precision must cover a full local calendar day")
        return self


class ResearchSnapshot(Evidence):
    """One source's evidence for a symbol, event kinds and coverage interval.

    EMPTY asserts a complete successful query, never a provider failure.
    STALE may retain old evidence. UNAVAILABLE contains no usable events.
    All times are explicit; callers must build a new snapshot at each as_of.
    """

    schema_version: Literal[1] = 1
    symbol: str = Field(min_length=1)
    source: str = Field(min_length=1)
    kinds: tuple[EventKind, ...]
    coverage_start: AwareDatetime
    coverage_end: AwareDatetime
    as_of: AwareDatetime
    observed_at: AwareDatetime
    fresh_until: AwareDatetime
    knowledge_provenance: KnowledgeProvenance
    status: ResearchStatus
    events: tuple[ResearchEvent, ...] = ()
    """All visible revisions, including cancellations; use active_events for event presence."""

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if not self.kinds or len(set(self.kinds)) != len(self.kinds):
            raise ValueError("query kinds must be nonempty and unique")
        if self.coverage_start >= self.coverage_end:
            raise ValueError("coverage interval must be nonempty")
        if self.observed_at > self.as_of or self.fresh_until < self.observed_at:
            raise ValueError("invalid observation or freshness interval")
        if (
            self.status in (ResearchStatus.AVAILABLE, ResearchStatus.EMPTY)
            and self.as_of >= self.fresh_until
        ):
            raise ValueError("expired evidence must be marked stale")
        if self.status is ResearchStatus.STALE and self.as_of < self.fresh_until:
            raise ValueError("stale evidence has not expired")
        if self.status is ResearchStatus.AVAILABLE and not self.events:
            raise ValueError("available requires events; use empty for verified absence")
        if self.status in (ResearchStatus.EMPTY, ResearchStatus.UNAVAILABLE) and self.events:
            raise ValueError("empty/unavailable cannot contain events")
        seen: set[str] = set()
        for event in self.events:
            if event.symbol != self.symbol or event.source != self.source:
                raise ValueError("event does not belong to snapshot symbol/source")
            if event.kind not in self.kinds:
                raise ValueError("event kind is outside query scope")
            if event.known_at > self.observed_at:
                raise ValueError("event revision was not known when snapshot was observed")
            if event.event_start >= self.coverage_end or event.event_end <= self.coverage_start:
                raise ValueError("event is outside coverage")
            if event.event_id in seen:
                raise ValueError("only one revision per event is allowed")
            seen.add(event.event_id)
        return self

    @property
    def active_events(self) -> tuple[ResearchEvent, ...]:
        """Non-cancelled events; cancellations remain in events for audit and identity.

        AVAILABLE describes available evidence, not an active catalyst. Likewise,
        has_verified_knowledge describes provenance, not whether an event is active.
        """
        return tuple(event for event in self.events if not event.cancelled)

    @property
    def snapshot_id(self) -> str:
        """Versioned content hash, independent of event order and timezone spelling."""
        payload = self.model_dump(mode="json")
        for field in ("coverage_start", "coverage_end", "as_of", "observed_at", "fresh_until"):
            payload[field] = getattr(self, field).astimezone(UTC).isoformat()
        payload["kinds"] = sorted(self.kinds)
        events = []
        for event in sorted(self.events, key=lambda item: item.event_id):
            value = event.model_dump(mode="json")
            for field in ("event_start", "event_end", "known_at", "published_at"):
                timestamp = getattr(event, field)
                value[field] = timestamp.astimezone(UTC).isoformat() if timestamp else None
            events.append(value)
        payload["events"] = events
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "research-v1:" + hashlib.sha256(encoded).hexdigest()

    @property
    def has_verified_knowledge(self) -> bool:
        """Necessary research eligibility, NOT a strategy promotion decision."""
        return (
            self.status in (ResearchStatus.AVAILABLE, ResearchStatus.EMPTY)
            and self.knowledge_provenance is KnowledgeProvenance.OBSERVED
            and all(
                event.knowledge_provenance is KnowledgeProvenance.OBSERVED for event in self.events
            )
        )
