SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE job_executions ADD COLUMN IF NOT EXISTS project_code VARCHAR(30);

-- Backfill from kwargs: profiling jobs reference table_groups, test jobs reference test_suites
UPDATE job_executions je
   SET project_code = tg.project_code
  FROM table_groups tg
 WHERE je.project_code IS NULL
   AND je.job_key = 'run-profile'
   AND tg.id = (je.kwargs->>'table_group_id')::UUID;

UPDATE job_executions je
   SET project_code = ts.project_code
  FROM test_suites ts
 WHERE je.project_code IS NULL
   AND je.job_key IN ('run-tests', 'run-monitors', 'run-test-generation')
   AND ts.id = (je.kwargs->>'test_suite_id')::UUID;

-- Any remaining rows (orphaned references) get a placeholder so NOT NULL can be applied
UPDATE job_executions SET project_code = 'unknown' WHERE project_code IS NULL;

ALTER TABLE job_executions ALTER COLUMN project_code SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_job_executions_project
    ON job_executions (project_code, created_at DESC);
