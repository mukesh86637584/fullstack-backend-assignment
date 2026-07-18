from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class RecordType(str, Enum):
    CONTACT = "contact"
    DEAL = "deal"
    PAYMENT = "payment"
    EVENT = "event"


@dataclass
class NormalizedRecord:
    source: str
    source_id: str
    record_type: RecordType
    email: str | None = None
    name: str | None = None
    amount_cents: int | None = None
    currency: str = "usd"
    status: str | None = None
    event_start: datetime | None = None
    event_end: datetime | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    source_updated_at: datetime | None = None


@dataclass
class FetchResult:
    records: list[NormalizedRecord]
    next_cursor: str | None = None


class StaleCursorError(Exception):
    """Raised when incremental cursor is rejected (410, expired token, etc.)."""


class SourceFetchError(Exception):
    """Raised when a source returns unrecoverable garbage."""
