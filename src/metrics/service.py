from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Literal

from src.db.connection import acquire
from src.metrics.revenue_definition import BreakdownGranularity, build_revenue_filter_clause, collected_status_sql_param

BreakdownGranularity = Literal["day", "week"]


@dataclass
class RevenueSummary:
    start_date: date
    end_date: date
    total_cents: int
    transaction_count: int
    currency: str = "usd"


@dataclass
class RevenueBreakdownRow:
    period_start: date
    total_cents: int
    transaction_count: int


@dataclass
class RevenueBreakdown:
    start_date: date
    end_date: date
    granularity: BreakdownGranularity
    rows: list[RevenueBreakdownRow]
    currency: str = "usd"

    @property
    def total_cents(self) -> int:
        return sum(r.total_cents for r in self.rows)


def _utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    return start_dt, end_dt


def _base_where_clause() -> str:
    return f"""
        collected_at IS NOT NULL
        AND collected_at >= $1
        AND collected_at <= $2
        AND {build_revenue_filter_clause()}
    """


async def compute_revenue_summary(start: date, end: date) -> RevenueSummary:
    """
    Compute total collected revenue for a date range.
    Uses the canonical allow-list from revenue_definition.
    """
    start_dt, end_dt = _utc_bounds(start, end)
    statuses = collected_status_sql_param()

    async with acquire() as conn:
        row = await conn.fetchrow(
            f"""
            SELECT
                COALESCE(SUM(amount_cents), 0)::bigint AS total_cents,
                COUNT(*)::int AS transaction_count
            FROM normalized_transactions
            WHERE {_base_where_clause()}
            """,
            start_dt,
            end_dt,
            statuses,
        )

    return RevenueSummary(
        start_date=start,
        end_date=end,
        total_cents=row["total_cents"],
        transaction_count=row["transaction_count"],
    )


async def compute_revenue_breakdown(
    start: date,
    end: date,
    granularity: BreakdownGranularity = "day",
) -> RevenueBreakdown:
    """
    Day-by-day or week-by-week breakdown using the SAME filter as summary.
    """
    start_dt, end_dt = _utc_bounds(start, end)
    statuses = collected_status_sql_param()
    trunc = "day" if granularity == "day" else "week"

    async with acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                DATE_TRUNC('{trunc}', collected_at AT TIME ZONE 'UTC')::date AS period_start,
                COALESCE(SUM(amount_cents), 0)::bigint AS total_cents,
                COUNT(*)::int AS transaction_count
            FROM normalized_transactions
            WHERE {_base_where_clause()}
            GROUP BY 1
            ORDER BY 1
            """,
            start_dt,
            end_dt,
            statuses,
        )

    return RevenueBreakdown(
        start_date=start,
        end_date=end,
        granularity=granularity,
        rows=[
            RevenueBreakdownRow(
                period_start=r["period_start"],
                total_cents=r["total_cents"],
                transaction_count=r["transaction_count"],
            )
            for r in rows
        ],
    )
