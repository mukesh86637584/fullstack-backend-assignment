"""
CANONICAL REVENUE DEFINITION — single source of truth.

All revenue calculations MUST import from this module.
Do not duplicate status logic elsewhere; tests enforce this.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

# Allow-list: only these statuses count as collected revenue.
# New or unexpected statuses are excluded by default (fail-safe).
COLLECTED_STATUS_ALLOWLIST: frozenset[str] = frozenset(
    {
        "paid",
        "succeeded",
        "completed",
        "captured",
    }
)

BreakdownGranularity = Literal["day", "week"]


def is_collected_status(status: str) -> bool:
    return status.lower().strip() in COLLECTED_STATUS_ALLOWLIST


def collected_status_sql_param() -> list[str]:
    """Return allow-list as a list for SQL ANY($n) binding."""
    return sorted(COLLECTED_STATUS_ALLOWLIST)


def build_revenue_filter_clause(status_column: str = "status", param_index: int = 3) -> str:
    """
    Shared SQL fragment for filtering collected transactions.
    Both summary and breakdown queries MUST use this function.
    """
    return f"LOWER(TRIM({status_column})) = ANY(${param_index}::text[])"


def parse_date_range(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive date range converted to UTC datetimes."""
    start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=datetime.now().astimezone().tzinfo)
    end_dt = datetime.combine(end, datetime.max.time()).replace(tzinfo=datetime.now().astimezone().tzinfo)
    return start_dt, end_dt
