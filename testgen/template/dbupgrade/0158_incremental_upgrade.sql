SET SEARCH_PATH TO {SCHEMA_NAME};

DROP VIEW IF EXISTS v_latest_profile_results CASCADE;
DROP VIEW IF EXISTS v_queued_observability_results CASCADE;
DROP VIEW IF EXISTS v_test_results CASCADE;

DROP SEQUENCE profile_results_dk_id_seq;
DROP SEQUENCE test_definitions_cat_test_id_seq;

DROP TABLE working_agg_cat_tests;
DROP TABLE working_agg_cat_results;

ALTER TABLE profile_results
    DROP COLUMN dk_id;

ALTER TABLE test_suites
    DROP COLUMN test_action,
    DROP COLUMN test_suite_schema;

ALTER TABLE test_definitions
    DROP CONSTRAINT test_definitions_cat_test_id_pk,
    DROP COLUMN cat_test_id,
    DROP COLUMN test_action,
    ADD CONSTRAINT test_definitions_id_pk PRIMARY KEY (id);

ALTER TABLE test_runs
    DROP COLUMN duration,
    ADD COLUMN progress JSONB;

ALTER TABLE test_results
    ALTER COLUMN result_message TYPE VARCHAR,
    DROP COLUMN starttime,
    DROP COLUMN endtime,
    DROP COLUMN test_action,
    DROP COLUMN subset_condition,
    DROP COLUMN result_error_data,
    DROP COLUMN result_query;

UPDATE job_schedules
    SET kwargs = jsonb_build_object('test_suite_id', test_suites.id)
FROM test_suites
WHERE job_schedules.key = 'run-tests'
    AND job_schedules.kwargs->>'project_key' = test_suites.project_code
    AND job_schedules.kwargs->>'test_suite_key' = test_suites.test_suite;
