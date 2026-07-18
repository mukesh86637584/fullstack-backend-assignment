# Full-Stack Backend Assignment

Backend-focused implementation covering:

1. **Multi-source sync pipeline** — HubSpot CRM, Stripe payments, Google Calendar → one normalized schema
2. **Revenue metrics service** — canonical "collected" definition with allow-list statuses, summary + breakdown views that always agree

No UI required. Operate via CLI or HTTP API (curl/Postman).

## Architecture

```
┌─────────────┐  ┌─────────────┐  ┌──────────────────┐
│   HubSpot   │  │   Stripe    │  │ Google Calendar  │
│    (CRM)    │  │ (payments)  │  │    (events)      │
└──────┬──────┘  └──────┬──────┘  └────────┬─────────┘
       │                │                   │
       └────────────────┼───────────────────┘
                        ▼
              ┌─────────────────────┐
              │   Sync Pipeline     │
              │  • incremental fetch│
              │  • stale → backfill │
              │  • idempotent upsert│
              │  • per-source errors│
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │  Supabase Postgres  │
              │  normalized_records │
              │  sync_cursors       │
              │  normalized_txns    │
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │  Revenue Metrics    │
              │  (single definition)│
              └──────────┬──────────┘
                         ▼
         ┌───────────────┴───────────────┐
         ▼                               ▼
  GET /metrics/revenue/summary   GET /metrics/revenue/breakdown
```

## Quick Start (local with mocks)

```bash
cd fullstack-backend-assignment

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start Postgres
docker compose up -d

cp .env.example .env
# DATABASE_URL=postgresql://postgres:postgres@localhost:5433/assignment
# USE_MOCK_SOURCES=true

# Run sync pipeline
PYTHONPATH=. python -m src.cli.main sync

# Ingest sample transactions (Stripe + mock finance sources)
PYTHONPATH=. python -m src.cli.main ingest

# Verify summary == breakdown
PYTHONPATH=. python -m src.cli.main revenue --start 2026-07-01 --end 2026-07-31

# Run tests
PYTHONPATH=. pytest -v
```

## API Server

```bash
PYTHONPATH=. uvicorn src.api.main:app --reload --port 8000
```

## Deploy to Render

This repo includes a [Render Blueprint](https://render.com/docs/infrastructure-as-code) (`render.yaml`) that provisions:

- **Web service** — FastAPI on the free tier (`fullstack-backend-api`)
- **Postgres** — managed database wired via `DATABASE_URL` (`assignment-db`)

Migrations run automatically on API startup.

### Steps

1. Push this repo to GitHub (or GitLab/Bitbucket).
2. In [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**.
3. Connect the repo and apply the blueprint (Render reads `render.yaml`).
4. Wait for the web service deploy to finish, then open its `*.onrender.com` URL.

### Verify deployment

```bash
curl https://YOUR-SERVICE.onrender.com/health
curl -X POST https://YOUR-SERVICE.onrender.com/sync/run
curl -X POST https://YOUR-SERVICE.onrender.com/transactions/ingest
curl "https://YOUR-SERVICE.onrender.com/metrics/revenue/summary?start=2026-07-01&end=2026-07-31"
```

By default `USE_MOCK_SOURCES=true` so the service works without HubSpot/Stripe/Google credentials. To use real APIs, set `USE_MOCK_SOURCES=false` and add the keys from `.env.example` in the Render service **Environment** tab.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sync/run` | Run full multi-source sync |
| POST | `/transactions/ingest` | Pull & normalize transactions |
| GET | `/metrics/revenue/summary?start=2026-07-01&end=2026-07-31` | Total collected revenue |
| GET | `/metrics/revenue/breakdown?start=2026-07-01&end=2026-07-31&granularity=day` | Daily/weekly breakdown |
| GET | `/health` | Health check |

### Example curl

```bash
curl -X POST http://localhost:8000/sync/run
curl -X POST http://localhost:8000/transactions/ingest
curl "http://localhost:8000/metrics/revenue/summary?start=2026-07-01&end=2026-07-31"
curl "http://localhost:8000/metrics/revenue/breakdown?start=2026-07-01&end=2026-07-31&granularity=day"
```

## Problem 1: Sync Pipeline Design

### Normalized schema

All sources map into `normalized_records` with `(source, source_id)` as the idempotency key.

| Field | HubSpot | Stripe | Google Calendar |
|-------|---------|--------|-----------------|
| `record_type` | contact | payment | event |
| `email` | contact email | billing email | organizer email |
| `name` | first + last | billing name | event summary |
| `amount_cents` | — | charge amount | — |
| `status` | — | charge status | event status |
| `event_start/end` | — | — | event times |

### Stale cursor → full backfill

When incremental fetch raises `StaleCursorError` (HTTP 410, expired sync token), the pipeline automatically runs `fetch_full()` instead of crashing or silently skipping data.

### Idempotent writes

`INSERT ... ON CONFLICT (source, source_id) DO UPDATE` ensures webhooks and back-to-back sync runs never create duplicate rows.

### Fault isolation

Each source syncs independently. If HubSpot is down or Stripe returns garbage, the other sources still persist their data.

## Problem 2: Revenue Metrics Design

### Canonical definition (allow-list)

Only these statuses count as collected revenue (defined once in `src/metrics/revenue_definition.py`):

- `paid`
- `succeeded`
- `completed`
- `captured`

Any new or unexpected status (e.g. `refunded`, `voided`, `brand_new_status`) is **excluded by default** — not silently counted.

### Two views, one computation

Both `/metrics/revenue/summary` and `/metrics/revenue/breakdown` call shared SQL built from `build_revenue_filter_clause()` and `collected_status_sql_param()`. The breakdown total always equals the summary total.

### Drift detection

- `tests/test_revenue_guardrails.py` scans the codebase for exclusion-list patterns (`status !=`, `NOT IN`, etc.) outside the canonical module
- `tests/test_revenue.py` asserts summary == breakdown after every change
- CLI `revenue` command prints a mismatch warning

## Connecting Real APIs

Set `USE_MOCK_SOURCES=false` and provide credentials in `.env`:

### HubSpot (free developer account)

1. Create account at [developers.hubspot.com](https://developers.hubspot.com/)
2. Create a private app with `crm.objects.contacts.read` scope
3. Seed a few contacts via the HubSpot UI or API
4. Set `HUBSPOT_ACCESS_TOKEN`

### Stripe (test mode)

1. Get test keys from [dashboard.stripe.com/test/apikeys](https://dashboard.stripe.com/test/apikeys)
2. Create test charges via Dashboard or `stripe trigger payment_intent.succeeded`
3. Set `STRIPE_SECRET_KEY=sk_test_...`

### Google Calendar

1. Enable Calendar API in [Google Cloud Console](https://console.cloud.google.com/)
2. Create OAuth credentials or a service account
3. Seed a few events on your calendar
4. Set `GOOGLE_*` env vars (see `.env.example`)

### Supabase Postgres

1. Create a free project at [supabase.com](https://supabase.com/)
2. Copy the connection string from Settings → Database
3. Set `DATABASE_URL=postgresql://postgres:...@db....supabase.co:5432/postgres`

Migrations run automatically on API startup and via CLI commands.

## Project Structure

```
src/
├── sync/
│   ├── pipeline.py          # Orchestrator (fault-isolated)
│   ├── storage.py           # Cursors + idempotent upsert
│   ├── models.py            # NormalizedRecord, errors
│   └── sources/
│       ├── hubspot.py       # Real HubSpot/Stripe/Calendar adapters
│       └── mock.py          # Deterministic mock data for dev/tests
├── metrics/
│   ├── revenue_definition.py  # SINGLE SOURCE OF TRUTH for "collected"
│   ├── service.py             # Summary + breakdown queries
│   └── ingest.py              # Stripe + mock finance ingestion
├── api/main.py              # FastAPI endpoints
└── cli/main.py              # CLI commands
tests/
├── test_sync.py             # Idempotency, stale cursor, resilience
├── test_revenue.py          # Allow-list, summary == breakdown
└── test_revenue_guardrails.py  # Detect duplicate metric logic
```
