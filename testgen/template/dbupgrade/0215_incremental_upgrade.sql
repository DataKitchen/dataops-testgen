SET SEARCH_PATH TO {SCHEMA_NAME};

-- 'resume_requested' releases a human pause, so the poll has to claim it and the partial index
-- must list it or Postgres cannot use the index for the poll query. 'pause_requested' and
-- 'paused' are held rather than claimed, so they stay out.
DROP INDEX IF EXISTS idx_job_executions_poll;
CREATE INDEX idx_job_executions_poll ON job_executions (created_at)
    WHERE status IN ('pending', 'interrupted', 'resume_requested', 'cancel_requested');

-- Seconds a job spent working, accumulated across however many processes ran it. A run that
-- stops and continues spans more wall-clock time than it works, and once the stop is one
-- somebody asked for the gap is unbounded, so start-to-end cannot answer how long it took.
ALTER TABLE job_executions
    ADD COLUMN IF NOT EXISTS active_seconds DOUBLE PRECISION;

-- Backfill runs that finished before the column existed, so every display can read it alone.
-- Anchored on the claim, which is where the live accumulator measures from; a run that stopped
-- and continued keeps only its last segment, because no row written before this carries the
-- earlier ones.
UPDATE job_executions
   SET active_seconds = EXTRACT(EPOCH FROM (completed_at - COALESCE(claimed_at, started_at)))
 WHERE active_seconds IS NULL
   AND started_at IS NOT NULL
   AND completed_at IS NOT NULL;
