SET SEARCH_PATH TO {SCHEMA_NAME};

UPDATE job_schedules
    SET kwargs = kwargs - 'project_code' || jsonb_build_object('project_key', kwargs->'project_code')
WHERE key = 'run-tests';
