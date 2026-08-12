SET SEARCH_PATH TO {SCHEMA_NAME};

-- The poll index was partial on status = 'pending', but the claim query selects
-- status IN ('pending', 'cancel_requested'). Postgres only uses a partial index when the query
-- predicate implies the index predicate, and an IN-list does not imply equality, so this index
-- never served that query. Rebuild it over the statuses the claim query looks for, keyed on
-- created_at alone so the poll's ordered limit is answered by the index rather than a sort.
DROP INDEX IF EXISTS idx_job_executions_poll;
CREATE INDEX idx_job_executions_poll ON job_executions (created_at)
    WHERE status IN ('pending', 'cancel_requested');
