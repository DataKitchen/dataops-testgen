SET SEARCH_PATH TO {SCHEMA_NAME};

-- TG-1025: Backfill job_execution_id for historical test runs and profiling runs
-- created before the job execution queue (TG-1002).

-- 1. Backfill test_runs: create job_executions and link them
DO $$
DECLARE
    r RECORD;
    new_id UUID;
    mapped_status TEXT;
BEGIN
    FOR r IN
        SELECT tr.id AS run_id,
               tr.test_starttime,
               tr.test_endtime,
               tr.status,
               ts.id AS suite_id,
               ts.project_code
        FROM test_runs tr
        JOIN test_suites ts ON tr.test_suite_id = ts.id
        WHERE tr.job_execution_id IS NULL
    LOOP
        new_id := gen_random_uuid();
        mapped_status := CASE r.status
            WHEN 'Complete' THEN 'completed'
            WHEN 'Cancelled' THEN 'canceled'
            ELSE 'error'
        END;

        INSERT INTO job_executions (id, job_key, kwargs, source, status, project_code, created_at, started_at, completed_at)
        VALUES (
            new_id,
            'run-tests',
            jsonb_build_object('test_suite_id', r.suite_id::text),
            'backfill',
            mapped_status,
            r.project_code,
            COALESCE(r.test_starttime, NOW()),
            r.test_starttime,
            r.test_endtime
        );

        UPDATE test_runs SET job_execution_id = new_id WHERE id = r.run_id;
    END LOOP;
END
$$;

-- 2. Backfill profiling_runs: create job_executions and link them
DO $$
DECLARE
    r RECORD;
    new_id UUID;
    mapped_status TEXT;
BEGIN
    FOR r IN
        SELECT pr.id AS run_id,
               pr.profiling_starttime,
               pr.profiling_endtime,
               pr.status,
               pr.table_groups_id,
               pr.project_code
        FROM profiling_runs pr
        WHERE pr.job_execution_id IS NULL
    LOOP
        new_id := gen_random_uuid();
        mapped_status := CASE r.status
            WHEN 'Complete' THEN 'completed'
            WHEN 'Cancelled' THEN 'canceled'
            ELSE 'error'
        END;

        INSERT INTO job_executions (id, job_key, kwargs, source, status, project_code, created_at, started_at, completed_at)
        VALUES (
            new_id,
            'run-profile',
            jsonb_build_object('table_group_id', r.table_groups_id::text),
            'backfill',
            mapped_status,
            r.project_code,
            COALESCE(r.profiling_starttime, NOW()),
            r.profiling_starttime,
            r.profiling_endtime
        );

        UPDATE profiling_runs SET job_execution_id = new_id WHERE id = r.run_id;
    END LOOP;
END
$$;
