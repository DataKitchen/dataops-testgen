SET SEARCH_PATH TO {SCHEMA_NAME};

-- Normalize job_executions status spelling: cancelled -> canceled (American English)
-- Covers rows created by migration 0184 backfill or by earlier code versions.
UPDATE job_executions SET status = 'canceled' WHERE status = 'cancelled';
