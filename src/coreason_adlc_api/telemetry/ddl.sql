
-- 6.4 Telemetry & Compliance (FR-API-008, FR-API-012)
CREATE SCHEMA IF NOT EXISTS telemetry;

CREATE TABLE IF NOT EXISTS telemetry.telemetry_logs (
    log_id UUID DEFAULT gen_random_uuid(),
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Metadata
    user_uuid UUID, -- Nullable if auth fails, but tracked for billing
    auc_id VARCHAR(50),
    model_name VARCHAR(100),

    -- Payloads (Scrubbed by Presidio)
    request_payload JSONB,
    response_payload JSONB,

    -- Metrics
    cost_usd DECIMAL(10, 6),
    latency_ms INTEGER
) PARTITION BY RANGE (timestamp);

-- Storage optimization for large JSON payloads
ALTER TABLE telemetry.telemetry_logs ALTER COLUMN request_payload SET STORAGE EXTENDED;
ALTER TABLE telemetry.telemetry_logs ALTER COLUMN response_payload SET STORAGE EXTENDED;

-- Example Partition (Automated via Cron/pg_partman in Prod)
-- For development/testing we create a default partition
CREATE TABLE IF NOT EXISTS telemetry.telemetry_logs_default PARTITION OF telemetry.telemetry_logs
    DEFAULT;
