SET SEARCH_PATH TO {SCHEMA_NAME};

-- Add data retention settings to projects.
-- Existing projects start disabled (NULL days); new projects default to enabled at 180 days,
-- enforced via ALTER COLUMN SET DEFAULT after the initial backfill.

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS data_retention_enabled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE projects
    ALTER COLUMN data_retention_enabled SET DEFAULT TRUE;

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS data_retention_days INTEGER;

ALTER TABLE projects
    ALTER COLUMN data_retention_days SET DEFAULT 180;

-- Indexes supporting data retention sweeps.
-- profiling_runs: retention filters by (project_code, profiling_starttime).
CREATE INDEX IF NOT EXISTS ix_prun_pc_starttime
    ON profiling_runs(project_code, profiling_starttime);

-- job_executions: supports retention queries filtering by
-- (project_code, completed_at).
CREATE INDEX IF NOT EXISTS idx_job_executions_project_completed
    ON job_executions(project_code, completed_at);
