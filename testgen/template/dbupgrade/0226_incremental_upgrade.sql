SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE job_executions
    ADD COLUMN IF NOT EXISTS in_process BOOLEAN NOT NULL DEFAULT FALSE;

-- 'queued' is claimable, so the poll selects it and the partial index must list it or Postgres
-- cannot use the index for the poll query.
DROP INDEX IF EXISTS idx_job_executions_poll;
CREATE INDEX idx_job_executions_poll ON job_executions (created_at)
    WHERE status IN ('pending', 'interrupted', 'resume_requested', 'queued', 'cancel_requested');
