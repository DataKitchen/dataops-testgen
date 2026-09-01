SET SEARCH_PATH TO {SCHEMA_NAME};

-- Checkpoint for a job that stopped at a work-key boundary and can continue later. The shape
-- is owned by the job that writes it; NULL means the next claim starts the job from scratch.
ALTER TABLE job_executions
    ADD COLUMN IF NOT EXISTS resume_state JSONB;

-- Room for the lifecycle status values; the longest is 'interrupt_requested' at 19 characters.
-- The view reads job_executions.status, and Postgres refuses to retype a column a view selects,
-- so it is dropped here and rebuilt from 060_create_standard_views.sql later in the upgrade.
DROP VIEW IF EXISTS v_latest_profile_results CASCADE;
ALTER TABLE job_executions
    ALTER COLUMN status TYPE VARCHAR(30);

-- The claim query selects status IN ('pending', 'interrupted', 'cancel_requested'); the poll
-- index's partial predicate must match that list or Postgres cannot use the index for the poll.
DROP INDEX IF EXISTS idx_job_executions_poll;
CREATE INDEX idx_job_executions_poll ON job_executions (created_at)
    WHERE status IN ('pending', 'interrupted', 'cancel_requested');

-- Whether a numeric column carries a fractional scale. It comes from the target's DDL and
-- decides whether the profiling query measures a fractional sum, so a run that reads the
-- catalog back instead of the target needs it recorded rather than re-derived.
ALTER TABLE stg_data_chars_updates
    ADD COLUMN IF NOT EXISTS is_decimal BOOLEAN;

ALTER TABLE data_column_chars
    ADD COLUMN IF NOT EXISTS is_decimal BOOLEAN;
