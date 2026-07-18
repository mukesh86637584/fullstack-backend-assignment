from __future__ import annotations

import logging
from dataclasses import dataclass

from src.config import should_use_mock
from src.sync.sources.base import DataSource
from src.sync.sources.hubspot import GoogleCalendarSource, HubSpotSource, StripePaymentsSource
from src.sync.sources.mock import MockGoogleCalendarSource, MockHubSpotSource, MockStripePaymentsSource
from src.sync.storage import SourceSyncResult, sync_source

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    results: list[SourceSyncResult]

    @property
    def total_written(self) -> int:
        return sum(r.records_written for r in self.results)

    @property
    def failed_sources(self) -> list[str]:
        return [r.source for r in self.results if r.error]


def build_sources(use_mock: bool | None = None) -> list[DataSource]:
    mock = should_use_mock(use_mock)
    if mock:
        return [
            MockHubSpotSource(),
            MockStripePaymentsSource(),
            MockGoogleCalendarSource(),
        ]
    return [HubSpotSource(), StripePaymentsSource(), GoogleCalendarSource()]


async def run_sync_pipeline(sources: list[DataSource] | None = None) -> PipelineResult:
    """Run sync for all sources independently — one failure does not block others."""
    sources = sources or build_sources()
    results: list[SourceSyncResult] = []

    for source in sources:
        logger.info("Syncing source: %s", source.name)
        result = await sync_source(source)
        results.append(result)
        if result.error:
            logger.warning("Source %s completed with error: %s", source.name, result.error)
        else:
            logger.info(
                "Source %s synced %d records via %s",
                source.name,
                result.records_written,
                result.mode,
            )

    return PipelineResult(results=results)
