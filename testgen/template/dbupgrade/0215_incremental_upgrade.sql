SET SEARCH_PATH TO {SCHEMA_NAME};

-- A run stopped at a task boundary parks in one of two places, depending on who asked for the
-- stop. 'resume_requested' belongs in the claim query's status list as the release step of a
-- human pause, so the poll index's partial predicate has to list it or Postgres cannot use the
-- index for the poll. 'pause_requested' and 'paused' are held rather than claimed, so they
-- stay out of both.
DROP INDEX IF EXISTS idx_job_executions_poll;
CREATE INDEX idx_job_executions_poll ON job_executions (created_at)
    WHERE status IN ('pending', 'interrupted', 'resume_requested', 'cancel_requested');
