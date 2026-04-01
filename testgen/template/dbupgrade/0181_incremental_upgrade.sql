SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE IF NOT EXISTS job_executions (
    id              UUID            NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    job_key         VARCHAR(100)    NOT NULL,
    args            JSONB           NOT NULL DEFAULT '[]'::jsonb,
    kwargs          JSONB           NOT NULL DEFAULT '{}'::jsonb,
    source          VARCHAR(20)     NOT NULL,
    status          VARCHAR(20)     NOT NULL DEFAULT 'pending',
    job_schedule_id UUID            REFERENCES job_schedules(id) ON DELETE SET NULL,
    error_message   TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    claimed_at      TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_job_executions_poll
    ON job_executions (status, created_at) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_job_executions_schedule
    ON job_executions (job_schedule_id);

ALTER TABLE profiling_runs
    ADD COLUMN IF NOT EXISTS job_execution_id UUID;

ALTER TABLE test_runs
    ADD COLUMN IF NOT EXISTS job_execution_id UUID;
