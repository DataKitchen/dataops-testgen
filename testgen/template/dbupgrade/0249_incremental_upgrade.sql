SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE job_executions ADD COLUMN IF NOT EXISTS owner_id UUID;
ALTER TABLE job_executions ADD COLUMN IF NOT EXISTS owner_label VARCHAR(200);
ALTER TABLE job_executions ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_job_executions_in_progress ON job_executions (id)
    WHERE status IN ('claimed', 'running', 'cancel_requested', 'interrupt_requested', 'pause_requested');
