SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE INDEX IF NOT EXISTS idx_job_executions_in_progress ON job_executions (id)
    WHERE status IN ('claimed', 'running', 'cancel_requested', 'interrupt_requested', 'pause_requested');
