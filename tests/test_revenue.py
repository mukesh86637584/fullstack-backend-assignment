from datetime import date

import pytest

from src.metrics.ingest import ingest_stripe_transactions
from src.metrics.revenue_definition import COLLECTED_STATUS_ALLOWLIST, is_collected_status
from src.metrics.service import compute_revenue_breakdown, compute_revenue_summary


@pytest.mark.asyncio
async def test_summary_and_breakdown_always_agree(setup_db):
    await ingest_stripe_transactions(use_mock=True)

    start = date(2026, 7, 1)
    end = date(2026, 7, 31)

    summary = await compute_revenue_summary(start, end)
    breakdown = await compute_revenue_breakdown(start, end)

    assert summary.total_cents == breakdown.total_cents
    assert summary.transaction_count == sum(r.transaction_count for r in breakdown.rows)


@pytest.mark.asyncio
async def test_allowlist_excludes_unknown_statuses(setup_db):
    await ingest_stripe_transactions(use_mock=True)

    start = date(2026, 7, 1)
    end = date(2026, 7, 31)
    summary = await compute_revenue_summary(start, end)

    # Mock data collected statuses:
    # stripe succeeded 5000 + quickbooks paid 7500 + square completed 9900 = 22400
    # Excluded: pending 3000, failed 2000, refunded 4500
    assert summary.total_cents == 22400
    assert summary.transaction_count == 3


def test_new_status_not_in_allowlist_is_excluded():
    assert not is_collected_status("refunded")
    assert not is_collected_status("pending")
    assert not is_collected_status("voided")
    assert not is_collected_status("brand_new_status")
    assert is_collected_status("paid")
    assert is_collected_status("SUCCEEDED")


def test_allowlist_is_explicit_not_exclusion_based():
    """Allow-list must be a positive set; unknown statuses default to excluded."""
    all_known_non_collected = {"pending", "voided", "refunded", "failed", "cancelled", "processing"}
    for status in all_known_non_collected:
        assert status not in COLLECTED_STATUS_ALLOWLIST


@pytest.mark.asyncio
async def test_weekly_breakdown_matches_summary(setup_db):
    await ingest_stripe_transactions(use_mock=True)

    start = date(2026, 7, 1)
    end = date(2026, 7, 31)

    summary = await compute_revenue_summary(start, end)
    weekly = await compute_revenue_breakdown(start, end, granularity="week")

    assert summary.total_cents == weekly.total_cents
