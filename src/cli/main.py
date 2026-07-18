#!/usr/bin/env python3
"""CLI entry point for sync pipeline and transaction ingest."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def cmd_sync() -> int:
    from src.db.connection import close_pool, run_migrations
    from src.sync.pipeline import run_sync_pipeline

    await run_migrations()
    result = await run_sync_pipeline()
    for r in result.results:
        status = "ERROR" if r.error else "OK"
        print(f"[{status}] {r.source}: {r.records_written} records ({r.mode})")
        if r.error:
            print(f"       {r.error}")
    await close_pool()
    return 1 if result.failed_sources else 0


async def cmd_ingest() -> int:
    from src.db.connection import close_pool, run_migrations
    from src.metrics.ingest import ingest_stripe_transactions, log_unknown_statuses

    await run_migrations()
    count = await ingest_stripe_transactions()
    unknown = await log_unknown_statuses()
    print(f"Ingested {count} transactions")
    if unknown:
        print(f"Non-collected statuses (excluded): {', '.join(unknown)}")
    await close_pool()
    return 0


async def cmd_revenue(start: str, end: str) -> int:
    from src.db.connection import close_pool, run_migrations
    from src.metrics.service import compute_revenue_breakdown, compute_revenue_summary

    await run_migrations()
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    summary = await compute_revenue_summary(start_date, end_date)
    breakdown = await compute_revenue_breakdown(start_date, end_date)

    print(f"Summary total:   ${summary.total_cents / 100:.2f} ({summary.transaction_count} txns)")
    print(f"Breakdown total: ${breakdown.total_cents / 100:.2f} ({sum(r.transaction_count for r in breakdown.rows)} txns)")

    if summary.total_cents != breakdown.total_cents:
        print("MISMATCH: summary and breakdown disagree!")
        await close_pool()
        return 1

    print("Summary and breakdown agree.")
    for row in breakdown.rows:
        print(f"  {row.period_start}: ${row.total_cents / 100:.2f}")
    await close_pool()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Backend assignment CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync", help="Run multi-source sync pipeline")
    sub.add_parser("ingest", help="Ingest transactions for revenue metrics")

    rev = sub.add_parser("revenue", help="Compare summary vs breakdown totals")
    rev.add_argument("--start", required=True)
    rev.add_argument("--end", required=True)

    args = parser.parse_args()

    if args.command == "sync":
        code = asyncio.run(cmd_sync())
    elif args.command == "ingest":
        code = asyncio.run(cmd_ingest())
    elif args.command == "revenue":
        code = asyncio.run(cmd_revenue(args.start, args.end))
    else:
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()
