from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from src.config import settings
from src.sync.models import FetchResult, NormalizedRecord, RecordType, StaleCursorError
from src.sync.sources.base import DataSource


class HubSpotSource(DataSource):
    name = "hubspot"

    def __init__(self, access_token: str | None = None) -> None:
        self._token = access_token or settings.hubspot_access_token
        self._base = "https://api.hubapi.com"

    async def fetch_incremental(self, cursor: str | None) -> FetchResult:
        params: dict[str, Any] = {"limit": 100, "properties": "email,firstname,lastname,lastmodifieddate"}
        if cursor:
            params["after"] = cursor

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base}/crm/v3/objects/contacts",
                headers={"Authorization": f"Bearer {self._token}"},
                params=params,
            )
            if resp.status_code == 410:
                raise StaleCursorError("HubSpot pagination cursor expired")
            resp.raise_for_status()
            data = resp.json()

        records = [self.normalize(item) for item in data.get("results", [])]
        paging = data.get("paging", {}).get("next", {})
        return FetchResult(records=records, next_cursor=paging.get("after"))

    async def fetch_full(self) -> FetchResult:
        all_records: list[NormalizedRecord] = []
        cursor: str | None = None
        while True:
            result = await self.fetch_incremental(cursor)
            all_records.extend(result.records)
            if not result.next_cursor:
                break
            cursor = result.next_cursor
        return FetchResult(records=all_records, next_cursor=None)

    def normalize(self, raw: dict) -> NormalizedRecord:
        props = raw.get("properties", {})
        first = props.get("firstname") or ""
        last = props.get("lastname") or ""
        name = f"{first} {last}".strip() or None
        updated = props.get("lastmodifieddate")
        source_updated_at = (
            datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None
        )
        return NormalizedRecord(
            source=self.name,
            source_id=str(raw["id"]),
            record_type=RecordType.CONTACT,
            email=props.get("email"),
            name=name,
            raw_payload=raw,
            source_updated_at=source_updated_at,
        )


class StripePaymentsSource(DataSource):
    name = "stripe"

    def __init__(self, secret_key: str | None = None) -> None:
        self._key = secret_key or settings.stripe_secret_key

    async def fetch_incremental(self, cursor: str | None) -> FetchResult:
        params: dict[str, Any] = {"limit": 100}
        if cursor:
            params["starting_after"] = cursor

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://api.stripe.com/v1/charges",
                auth=(self._key, ""),
                params=params,
            )
            if resp.status_code == 410:
                raise StaleCursorError("Stripe cursor no longer valid")
            resp.raise_for_status()
            data = resp.json()

        records = [self.normalize(item) for item in data.get("data", [])]
        has_more = data.get("has_more", False)
        next_cursor = data["data"][-1]["id"] if has_more and data.get("data") else None
        return FetchResult(records=records, next_cursor=next_cursor)

    async def fetch_full(self) -> FetchResult:
        all_records: list[NormalizedRecord] = []
        cursor: str | None = None
        while True:
            result = await self.fetch_incremental(cursor)
            all_records.extend(result.records)
            if not result.next_cursor:
                break
            cursor = result.next_cursor
        return FetchResult(records=all_records, next_cursor=None)

    def normalize(self, raw: dict) -> NormalizedRecord:
        created = raw.get("created")
        source_updated_at = (
            datetime.fromtimestamp(created, tz=timezone.utc) if created else None
        )
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
            source_updated_at=source_updated_at,
        )


class GoogleCalendarSource(DataSource):
    name = "google_calendar"

    def __init__(self) -> None:
        self._calendar_id = settings.google_calendar_id

    def _get_service(self):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        if settings.google_service_account_json:
            creds = service_account.Credentials.from_service_account_file(
                settings.google_service_account_json,
                scopes=["https://www.googleapis.com/auth/calendar.readonly"],
            )
            return build("calendar", "v3", credentials=creds, cache_discovery=False)

        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=None,
            refresh_token=settings.google_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    async def fetch_incremental(self, cursor: str | None) -> FetchResult:
        import asyncio

        time_min = cursor  # ISO8601 updatedMin equivalent via syncToken or timeMin
        loop = asyncio.get_event_loop()

        def _fetch() -> FetchResult:
            service = self._get_service()
            params: dict[str, Any] = {
                "calendarId": self._calendar_id,
                "singleEvents": True,
                "maxResults": 100,
            }
            if cursor:
                try:
                    params["syncToken"] = cursor
                except Exception:
                    params["timeMin"] = cursor
            else:
                params["timeMin"] = datetime.now(timezone.utc).replace(
                    year=datetime.now(timezone.utc).year - 1
                ).isoformat()

            try:
                events_result = service.events().list(**params).execute()
            except Exception as exc:
                if "410" in str(exc) or "Sync token" in str(exc):
                    raise StaleCursorError("Google Calendar sync token expired") from exc
                raise

            records = [self.normalize(item) for item in events_result.get("items", [])]
            return FetchResult(
                records=records,
                next_cursor=events_result.get("nextSyncToken"),
            )

        return await loop.run_in_executor(None, _fetch)

    async def fetch_full(self) -> FetchResult:
        import asyncio

        loop = asyncio.get_event_loop()

        def _fetch() -> FetchResult:
            service = self._get_service()
            events_result = (
                service.events()
                .list(
                    calendarId=self._calendar_id,
                    singleEvents=True,
                    maxResults=250,
                    timeMin=datetime.now(timezone.utc).replace(
                        year=datetime.now(timezone.utc).year - 2
                    ).isoformat(),
                )
                .execute()
            )
            records = [self.normalize(item) for item in events_result.get("items", [])]
            return FetchResult(
                records=records,
                next_cursor=events_result.get("nextSyncToken"),
            )

        return await loop.run_in_executor(None, _fetch)

    def normalize(self, raw: dict) -> NormalizedRecord:
        start = raw.get("start", {})
        end = raw.get("end", {})
        start_dt = _parse_google_datetime(start)
        end_dt = _parse_google_datetime(end)
        updated = raw.get("updated")
        source_updated_at = (
            datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None
        )
        return NormalizedRecord(
            source=self.name,
            source_id=raw["id"],
            record_type=RecordType.EVENT,
            name=raw.get("summary"),
            email=raw.get("organizer", {}).get("email"),
            event_start=start_dt,
            event_end=end_dt,
            status=raw.get("status"),
            raw_payload=raw,
            source_updated_at=source_updated_at,
        )


def _parse_google_datetime(part: dict) -> datetime | None:
    if "dateTime" in part:
        return datetime.fromisoformat(part["dateTime"].replace("Z", "+00:00"))
    if "date" in part:
        return datetime.fromisoformat(part["date"] + "T00:00:00+00:00")
    return None
