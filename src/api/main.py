from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse

from src.config import settings
from src.db.connection import close_pool, run_migrations
from src.metrics.ingest import ingest_stripe_transactions
from src.metrics.service import compute_revenue_breakdown, compute_revenue_summary
from src.sync.pipeline import run_sync_pipeline

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting API (use_mock_sources=%s)", settings.use_mock_sources)
    await run_migrations()
    yield
    await close_pool()


app = FastAPI(
    title="Full-Stack Backend Assignment",
    description="Sync pipeline + revenue metrics API",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.post("/sync/run")
async def trigger_sync():
    result = await run_sync_pipeline()
    return {
        "total_written": result.total_written,
        "failed_sources": result.failed_sources,
        "sources": [
            {
                "source": r.source,
                "records_written": r.records_written,
                "mode": r.mode,
                "error": r.error,
            }
            for r in result.results
        ],
    }


@app.post("/transactions/ingest")
async def trigger_transaction_ingest():
    count = await ingest_stripe_transactions()
    return {"transactions_ingested": count}


@app.get("/metrics/revenue/summary")
async def revenue_summary(
    start: date = Query(..., description="Start date (inclusive)"),
    end: date = Query(..., description="End date (inclusive)"),
):
    if start > end:
        raise HTTPException(status_code=400, detail="start must be <= end")
    summary = await compute_revenue_summary(start, end)
    return {
        "start_date": summary.start_date.isoformat(),
        "end_date": summary.end_date.isoformat(),
        "total_cents": summary.total_cents,
        "total_dollars": summary.total_cents / 100,
        "transaction_count": summary.transaction_count,
        "currency": summary.currency,
    }


@app.get("/metrics/revenue/breakdown")
async def revenue_breakdown(
    start: date = Query(...),
    end: date = Query(...),
    granularity: str = Query("day", pattern="^(day|week)$"),
):
    if start > end:
        raise HTTPException(status_code=400, detail="start must be <= end")
    breakdown = await compute_revenue_breakdown(start, end, granularity=granularity)  # type: ignore[arg-type]
    return {
        "start_date": breakdown.start_date.isoformat(),
        "end_date": breakdown.end_date.isoformat(),
        "granularity": breakdown.granularity,
        "total_cents": breakdown.total_cents,
        "total_dollars": breakdown.total_cents / 100,
        "transaction_count": sum(r.transaction_count for r in breakdown.rows),
        "currency": breakdown.currency,
        "rows": [
            {
                "period_start": r.period_start.isoformat(),
                "total_cents": r.total_cents,
                "total_dollars": r.total_cents / 100,
                "transaction_count": r.transaction_count,
            }
            for r in breakdown.rows
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
