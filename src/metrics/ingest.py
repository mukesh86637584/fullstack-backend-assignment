from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import asyncpg
import httpx

from src.config import settings
from src.db.connection import acquire
from src.metrics.revenue_definition import COLLECTED_STATUS_ALLOWLIST, is_collected_status

logger = logging.getLogger(__name__)


@dataclass
class NormalizedTransaction:
    source: str
    source_id: str
    amount_cents: int
    currency: str
    status: str
    collected_at: datetime | None
    raw_payload: dict


async def upsert_transaction(txn: NormalizedTransaction) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO normalized_transactions (
                source, source_id, amount_cents, currency, status, collected_at, raw_payload, synced_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, NOW())
            ON CONFLICT (source, source_id) DO UPDATE SET
                amount_cents = EXCLUDED.amount_cents,
                currency = EXCLUDED.currency,
                status = EXCLUDED.status,
                collected_at = EXCLUDED.collected_at,
                raw_payload = EXCLUDED.raw_payload,
                synced_at = NOW()
            """,
            txn.source,
            txn.source_id,
            txn.amount_cents,
            txn.currency,
            txn.status,
            txn.collected_at,
            json.dumps(txn.raw_payload),
        )


def normalize_stripe_charge(raw: dict) -> NormalizedTransaction:
    created = raw.get("created")
    collected_at = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
    return NormalizedTransaction(
        source="stripe",
        source_id=raw["id"],
        amount_cents=raw["amount"],
        currency=raw.get("currency", "usd"),
        status=raw.get("status", "unknown"),
        collected_at=collected_at,
        raw_payload=raw,
    )


def normalize_mock_invoice(raw: dict) -> NormalizedTransaction:
    """Second source with different status vocabulary (e.g. QuickBooks-style)."""
    return NormalizedTransaction(
        source=raw.get("source", "quickbooks_mock"),
        source_id=raw["id"],
        amount_cents=raw["amount_cents"],
        currency=raw.get("currency", "usd"),
        status=raw.get("status", "unknown"),
        collected_at=datetime.fromisoformat(raw["collected_at"].replace("Z", "+00:00")),
        raw_payload=raw,
    )


MOCK_INVOICES = [
    {
        "id": "inv-001",
        "source": "quickbooks_mock",
        "amount_cents": 7500,
        "currency": "usd",
        "status": "paid",
        "collected_at": "2026-07-03T10:00:00Z",
    },
    {
        "id": "inv-002",
        "source": "quickbooks_mock",
        "amount_cents": 3000,
        "currency": "usd",
        "status": "pending",
        "collected_at": "2026-07-04T10:00:00Z",
    },
    {
        "id": "inv-003",
        "source": "square_mock",
        "amount_cents": 9900,
        "currency": "usd",
        "status": "completed",
        "collected_at": "2026-07-06T15:00:00Z",
    },
    {
        "id": "inv-004",
        "source": "square_mock",
        "amount_cents": 4500,
        "currency": "usd",
        "status": "refunded",
        "collected_at": "2026-07-07T12:00:00Z",
    },
]


async def ingest_stripe_transactions(use_mock: bool | None = None) -> int:
    mock = settings.use_mock_sources if use_mock is None else use_mock
    count = 0

    if mock:
        mock_charges = [
            {
                "id": "ch_rev_001",
                "amount": 5000,
                "currency": "usd",
                "status": "succeeded",
                "created": int(datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc).timestamp()),
            },
            {
                "id": "ch_rev_002",
                "amount": 2000,
                "currency": "usd",
                "status": "failed",
                "created": int(datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc).timestamp()),
            },
        ]
        for raw in mock_charges:
            await upsert_transaction(normalize_stripe_charge(raw))
            count += 1
        for raw in MOCK_INVOICES:
            await upsert_transaction(normalize_mock_invoice(raw))
            count += 1
        return count

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            "https://api.stripe.com/v1/charges",
            auth=(settings.stripe_secret_key, ""),
            params={"limit": 100},
        )
        resp.raise_for_status()
        for raw in resp.json().get("data", []):
            await upsert_transaction(normalize_stripe_charge(raw))
            count += 1
    return count


async def log_unknown_statuses() -> list[str]:
    """Surface unexpected statuses so they don't silently become revenue."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT status FROM normalized_transactions
            WHERE LOWER(TRIM(status)) != ALL($1::text[])
            ORDER BY status
            """,
            list(COLLECTED_STATUS_ALLOWLIST),
        )
    unknown = [r["status"] for r in rows]
    for status in unknown:
        logger.info("Non-collected status observed (excluded from revenue): %s", status)
    return unknown
