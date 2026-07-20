from __future__ import annotations

from datetime import datetime, timezone

from src.sync.models import FetchResult, NormalizedRecord, RecordType, StaleCursorError, SourceFetchError
from src.sync.sources.base import DataSource


class MockHubSpotSource(DataSource):
    name = "hubspot"

    def __init__(self, fail: bool = False, stale_on_cursor: str | None = None) -> None:
        self._fail = fail
        self._stale_on_cursor = stale_on_cursor
        self._contacts = [
            {
                "id": "hs-001",
                "properties": {
                    "email": "alice@example.com",
                    "firstname": "Alice",
                    "lastname": "Nguyen",
                    "lastmodifieddate": "2026-07-01T10:00:00Z",
                },
            },
            {
                "id": "hs-002",
                "properties": {
                    "email": "bob@example.com",
                    "firstname": "Bob",
                    "lastname": "Smith",
                    "lastmodifieddate": "2026-07-10T14:30:00Z",
                },
            },
        ]

    async def fetch_incremental(self, cursor: str | None) -> FetchResult:
        if self._fail:
            raise SourceFetchError("HubSpot mock source is down")
        if cursor and self._stale_on_cursor and cursor == self._stale_on_cursor:
            raise StaleCursorError("Mock stale cursor")
        start = int(cursor) if cursor else 0
        batch = self._contacts[start : start + 1]
        next_cursor = str(start + 1) if start + 1 < len(self._contacts) else None
        return FetchResult(
            records=[self.normalize(c) for c in batch],
            next_cursor=next_cursor,
        )

    async def fetch_full(self) -> FetchResult:
        if self._fail:
            raise SourceFetchError("HubSpot mock source is down")
        return FetchResult(records=[self.normalize(c) for c in self._contacts])

    def normalize(self, raw: dict) -> NormalizedRecord:
        props = raw.get("properties", {})
        first = props.get("firstname") or ""
        last = props.get("lastname") or ""
        updated = props.get("lastmodifieddate")
        source_updated_at = (
            datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None
        )
        return NormalizedRecord(
            source=self.name,
            source_id=str(raw["id"]),
            record_type=RecordType.CONTACT,
            email=props.get("email"),
            name=f"{first} {last}".strip() or None,
            raw_payload=raw,
            source_updated_at=source_updated_at,
        )


class MockStripePaymentsSource(DataSource):
    name = "stripe"

    def __init__(self, fail: bool = False, return_garbage: bool = False) -> None:
        self._fail = fail
        self._return_garbage = return_garbage
        self._charges = [
            {
                "id": "ch_001",
                "amount": 5000,
                "currency": "usd",
                "status": "succeeded",
                "created": int(datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc).timestamp()),
                "billing_details": {"email": "alice@example.com", "name": "Alice Nguyen"},
            },
            {
                "id": "ch_002",
                "amount": 12000,
                "currency": "usd",
                "status": "pending",
                "created": int(datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc).timestamp()),
                "billing_details": {"email": "bob@example.com", "name": "Bob Smith"},
            },
        ]

    async def fetch_incremental(self, cursor: str | None) -> FetchResult:
        if self._fail:
            raise SourceFetchError("Stripe mock source is down")
        if self._return_garbage:
            raise SourceFetchError("Stripe returned malformed payload")
        start = 0 if not cursor else next(i for i, c in enumerate(self._charges) if c["id"] == cursor) + 1
        batch = self._charges[start : start + 1]
        next_cursor = batch[-1]["id"] if start + 1 < len(self._charges) and batch else None
        return FetchResult(
            records=[self.normalize(c) for c in batch],
            next_cursor=next_cursor,
        )

    async def fetch_full(self) -> FetchResult:
        if self._fail:
            raise SourceFetchError("Stripe mock source is down")
        return FetchResult(records=[self.normalize(c) for c in self._charges])

    def normalize(self, raw: dict) -> NormalizedRecord:
        created = raw.get("created")
        return NormalizedRecord(
            source=self.name,
            source_id=raw["id"],
            record_type=RecordType.PAYMENT,
            email=raw.get("billing_details", {}).get("email"),
            name=raw.get("billing_details", {}).get("name"),
            amount_cents=raw.get("amount"),
            currency=raw.get("currency", "usd"),
            status=raw.get("status"),
            raw_payload=raw,
            source_updated_at=(
                datetime.fromtimestamp(created, tz=timezone.utc) if created else None
            ),
        )


class MockGoogleCalendarSource(DataSource):
    name = "google_calendar"

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self._events = [
            {
                "id": "evt-001",
                "summary": "Q3 Kickoff",
                "status": "confirmed",
                "updated": "2026-07-02T08:00:00Z",
                "start": {"dateTime": "2026-07-15T10:00:00Z"},
                "end": {"dateTime": "2026-07-15T11:00:00Z"},
                "organizer": {"email": "team@example.com"},
            },
            {
                "id": "evt-002",
                "summary": "Customer Demo",
                "status": "confirmed",
                "updated": "2026-07-08T16:00:00Z",
                "start": {"dateTime": "2026-07-20T14:00:00Z"},
                "end": {"dateTime": "2026-07-20T15:00:00Z"},
                "organizer": {"email": "sales@example.com"},
            },
        ]

    async def fetch_incremental(self, cursor: str | None) -> FetchResult:
        if self._fail:
            raise SourceFetchError("Google Calendar mock source is down")
        if cursor == "expired-token":
            raise StaleCursorError("Google Calendar sync token expired")
        if cursor == "sync-v2":
            return FetchResult(records=[], next_cursor=None)
        return FetchResult(
            records=[self.normalize(e) for e in self._events],
            next_cursor="sync-v2",
        )

    async def fetch_full(self) -> FetchResult:
        if self._fail:
            raise SourceFetchError("Google Calendar mock source is down")
        return FetchResult(records=[self.normalize(e) for e in self._events], next_cursor="sync-v2")

    def normalize(self, raw: dict) -> NormalizedRecord:
        updated = raw.get("updated")
        start = raw.get("start", {})
        end = raw.get("end", {})
        return NormalizedRecord(
            source=self.name,
            source_id=raw["id"],
            record_type=RecordType.EVENT,
            name=raw.get("summary"),
            email=raw.get("organizer", {}).get("email"),
            event_start=datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")),
            event_end=datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00")),
            status=raw.get("status"),
            raw_payload=raw,
            source_updated_at=(
                datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None
            ),
        )
