import pytest

from src.sync.pipeline import run_sync_pipeline
from src.sync.sources.mock import MockGoogleCalendarSource, MockHubSpotSource, MockStripePaymentsSource


@pytest.mark.asyncio
async def test_sync_is_idempotent(setup_db):
    sources = [
        MockHubSpotSource(),
        MockStripePaymentsSource(),
        MockGoogleCalendarSource(),
    ]

    first = await run_sync_pipeline(sources)
    second = await run_sync_pipeline(sources)

    assert first.total_written > 0
    assert second.total_written > 0

    from src.db.connection import acquire

    async with acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM normalized_records")

    # 2 contacts + 2 payments + 2 events = 6 unique records
    assert count == 6
    assert not first.failed_sources
    assert not second.failed_sources


@pytest.mark.asyncio
async def test_stale_cursor_triggers_full_backfill(setup_db):
    source = MockHubSpotSource(stale_on_cursor="0")
    from src.sync.storage import get_cursor, save_cursor, sync_source

    await save_cursor("hubspot", "0")
    result = await sync_source(source)

    assert result.mode == "full_backfill"
    assert result.records_written == 2
    assert result.error is None

    cursor = await get_cursor("hubspot")
    assert cursor is None  # full fetch returns all at once


@pytest.mark.asyncio
async def test_one_source_down_does_not_block_others(setup_db):
    sources = [
        MockHubSpotSource(fail=True),
        MockStripePaymentsSource(),
        MockGoogleCalendarSource(),
    ]
    result = await run_sync_pipeline(sources)

    assert "hubspot" in result.failed_sources
    assert "stripe" not in result.failed_sources
    assert "google_calendar" not in result.failed_sources
    assert result.total_written > 0

    from src.db.connection import acquire

    async with acquire() as conn:
        sources_in_db = await conn.fetch("SELECT DISTINCT source FROM normalized_records")

    source_names = {r["source"] for r in sources_in_db}
    assert "stripe" in source_names
    assert "google_calendar" in source_names
    assert "hubspot" not in source_names


@pytest.mark.asyncio
async def test_garbage_source_does_not_crash_pipeline(setup_db):
    sources = [
        MockHubSpotSource(),
        MockStripePaymentsSource(return_garbage=True),
        MockGoogleCalendarSource(),
    ]
    result = await run_sync_pipeline(sources)

    assert "stripe" in result.failed_sources
    assert result.total_written > 0
