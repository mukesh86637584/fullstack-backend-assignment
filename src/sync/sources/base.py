from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.sync.models import FetchResult, NormalizedRecord


class DataSource(ABC):
    """Contract for incremental + full fetch from an external system."""

    name: str

    @abstractmethod
    async def fetch_incremental(self, cursor: str | None) -> FetchResult:
        """Return records changed since cursor. Raise StaleCursorError if cursor is invalid."""

    @abstractmethod
    async def fetch_full(self) -> FetchResult:
        """Return all records for backfill."""

    @abstractmethod
    def normalize(self, raw: dict) -> NormalizedRecord:
        """Map source-specific shape to normalized schema."""
