SET SEARCH_PATH TO {SCHEMA_NAME};

-- Drop the unused `args` column from job_schedules and job_executions.
-- It's vestigial: exec_job dispatches via handler(**je.kwargs); no path reads args.
-- The job_schedules UNIQUE constraint includes args, so resolve and drop it dynamically
-- (the auto-generated PG constraint name varies with truncation).

DO $$
DECLARE c_name TEXT;
BEGIN
    SELECT conname INTO c_name
    FROM pg_constraint
    WHERE conrelid = 'job_schedules'::regclass
      AND contype = 'u'
      AND conkey @> ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid = 'job_schedules'::regclass AND attname = 'args')];
    IF c_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE job_schedules DROP CONSTRAINT %I', c_name);
    END IF;
END $$;

ALTER TABLE job_schedules DROP COLUMN args;

ALTER TABLE job_schedules
    ADD CONSTRAINT job_schedules_uniq UNIQUE (project_code, key, kwargs, cron_expr, cron_tz);

ALTER TABLE job_executions DROP COLUMN args;
