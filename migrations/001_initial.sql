-- Normalized records from CRM, payments, and calendar sources (Problem 1)
CREATE TABLE IF NOT EXISTS normalized_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    email TEXT,
    name TEXT,
    amount_cents BIGINT,
    currency TEXT DEFAULT 'usd',
    status TEXT,
    event_start TIMESTAMPTZ,
    event_end TIMESTAMPTZ,
    raw_payload JSONB,
    source_updated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_normalized_records_source_id UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_normalized_records_source ON normalized_records (source);
CREATE INDEX IF NOT EXISTS idx_normalized_records_updated ON normalized_records (source_updated_at);

-- Sync cursor state per source
CREATE TABLE IF NOT EXISTS sync_cursors (
    source TEXT PRIMARY KEY,
    cursor_value TEXT,
    last_sync_at TIMESTAMPTZ,
    last_full_sync_at TIMESTAMPTZ
);

-- Normalized transactions for revenue metrics (Problem 2)
CREATE TABLE IF NOT EXISTS normalized_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    amount_cents BIGINT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'usd',
    status TEXT NOT NULL,
    collected_at TIMESTAMPTZ,
    raw_payload JSONB,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_normalized_transactions_source_id UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_normalized_transactions_collected ON normalized_transactions (collected_at);
CREATE INDEX IF NOT EXISTS idx_normalized_transactions_status ON normalized_transactions (status);
