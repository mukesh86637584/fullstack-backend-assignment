from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import asyncpg

from src.db.connection import acquire
from src.sync.models import NormalizedRecord, StaleCursorError, SourceFetchError
from src.sync.sources.base import DataSource

logger = logging.getLogger(__name__)


@dataclass
class SourceSyncResult:
    source: str
    records_written: int
    mode: str  # "incremental" | "full_backfill"
    error: str | None = None


async def get_cursor(source: str) -> str | None:
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT cursor_value FROM sync_cursors WHERE source = $1", source)
        return row["cursor_value"] if row else None


async def save_cursor(source: str, cursor: str | None, full_sync: bool = False) -> None:
    now = datetime.now(timezone.utc)
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sync_cursors (source, cursor_value, last_sync_at, last_full_sync_at)
            VALUES ($1, $2, $3, CASE WHEN $4 THEN $3 ELSE NULL END)
            ON CONFLICT (source) DO UPDATE SET
                cursor_value = EXCLUDED.cursor_value,
                last_sync_at = EXCLUDED.last_sync_at,
                last_full_sync_at = CASE
                    WHEN $4 THEN EXCLUDED.last_sync_at
                    ELSE sync_cursors.last_full_sync_at
                END
            """,
            source,
            cursor,
            now,
            full_sync,
        )


async def upsert_records(records: list[NormalizedRecord]) -> int:
    if not records:
        return 0

    async with acquire() as conn:
        async with conn.transaction():
            for record in records:
                await conn.execute(
                    """
                    INSERT INTO normalized_records (
                        source, source_id, record_type, email, name,
                        amount_cents, currency, status, event_start, event_end,
                        raw_payload, source_updated_at, synced_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, NOW()
                    )
                    ON CONFLICT (source, source_id) DO UPDATE SET
                        record_type = EXCLUDED.record_type,
                        email = EXCLUDED.email,
                        name = EXCLUDED.name,
                        amount_cents = EXCLUDED.amount_cents,
                        currency = EXCLUDED.currency,
                        status = EXCLUDED.status,
                        event_start = EXCLUDED.event_start,
                        event_end = EXCLUDED.event_end,
                        raw_payload = EXCLUDED.raw_payload,
                        source_updated_at = EXCLUDED.source_updated_at,
                        synced_at = NOW()
                    """,
                    record.source,
                    record.source_id,
                    record.record_type.value,
                    record.email,
                    record.name,
                    record.amount_cents,
                    record.currency,
                    record.status,
                    record.event_start,
                    record.event_end,
                    json.dumps(record.raw_payload),
                    record.source_updated_at,
                )
    return len(records)


async def sync_source(source: DataSource) -> SourceSyncResult:
    cursor = await get_cursor(source.name)
    mode = "incremental"
    all_records: list[NormalizedRecord] = []

    try:
        current_cursor = cursor
        while True:
            result = await source.fetch_incremental(current_cursor)
            all_records.extend(result.records)
            if not result.next_cursor:
                final_cursor = result.next_cursor
                break
            current_cursor = result.next_cursor
            final_cursor = result.next_cursor
    except StaleCursorError as exc:
        logger.warning("Stale cursor for %s, falling back to full backfill: %s", source.name, exc)
        mode = "full_backfill"
        backfill = await source.fetch_full()
        all_records = backfill.records
        final_cursor = backfill.next_cursor
    except SourceFetchError as exc:
        logger.error("Source %s failed: %s", source.name, exc)
        return SourceSyncResult(source=source.name, records_written=0, mode=mode, error=str(exc))

    try:
        written = await upsert_records(all_records)
        await save_cursor(source.name, final_cursor, full_sync=(mode == "full_backfill"))
        return SourceSyncResult(source=source.name, records_written=written, mode=mode)
    except Exception as exc:
        logger.exception("Failed to persist records for %s", source.name)
        return SourceSyncResult(source=source.name, records_written=0, mode=mode, error=str(exc))
