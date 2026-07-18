"""Unit tests that do not require Postgres."""

from datetime import date

import pytest

from src.metrics.revenue_definition import (
    COLLECTED_STATUS_ALLOWLIST,
    build_revenue_filter_clause,
    is_collected_status,
)
from src.sync.models import StaleCursorError
from src.sync.sources.mock import MockGoogleCalendarSource, MockHubSpotSource, MockStripePaymentsSource


@pytest.mark.asyncio
async def test_mock_hubspot_normalizes_contacts():
    source = MockHubSpotSource()
    result = await source.fetch_full()
    assert len(result.records) == 2
    assert all(r.record_type.value == "contact" for r in result.records)
    assert result.records[0].email == "alice@example.com"


@pytest.mark.asyncio
async def test_mock_stripe_normalizes_payments():
    source = MockStripePaymentsSource()
    result = await source.fetch_full()
    assert len(result.records) == 2
    assert result.records[0].amount_cents == 5000
    assert result.records[0].status == "succeeded"


@pytest.mark.asyncio
async def test_mock_calendar_normalizes_events():
    source = MockGoogleCalendarSource()
    result = await source.fetch_full()
    assert len(result.records) == 2
    assert result.records[0].name == "Q3 Kickoff"
    assert result.records[0].event_start is not None


@pytest.mark.asyncio
async def test_stale_cursor_raises_on_mock_hubspot():
    source = MockHubSpotSource(stale_on_cursor="0")
    with pytest.raises(StaleCursorError):
        await source.fetch_incremental("0")


@pytest.mark.asyncio
async def test_failed_source_raises_source_fetch_error():
    from src.sync.models import SourceFetchError

    source = MockStripePaymentsSource(fail=True)
    with pytest.raises(SourceFetchError):
        await source.fetch_full()


def test_revenue_allowlist_is_positive_set():
    assert "paid" in COLLECTED_STATUS_ALLOWLIST
    assert "pending" not in COLLECTED_STATUS_ALLOWLIST
    assert "refunded" not in COLLECTED_STATUS_ALLOWLIST


def test_shared_sql_filter_uses_parameterized_allowlist():
    clause = build_revenue_filter_clause(param_index=3)
    assert "$3::text[]" in clause
    assert "NOT IN" not in clause.upper()


def test_is_collected_status_case_insensitive():
    assert is_collected_status("PAID")
    assert is_collected_status("Succeeded")
    assert not is_collected_status("failed")
