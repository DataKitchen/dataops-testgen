SET SEARCH_PATH TO {SCHEMA_NAME};

DROP VIEW IF EXISTS v_latest_profile_results CASCADE;
DROP VIEW IF EXISTS v_latest_profile_anomalies;
DROP VIEW IF EXISTS v_profiling_runs;
DROP VIEW IF EXISTS v_test_runs;

ALTER TABLE stg_data_chars_updates
    DROP COLUMN project_code,
    DROP COLUMN functional_table_type,
    DROP COLUMN functional_data_type,
    ADD COLUMN approx_record_ct BIGINT;

ALTER TABLE data_table_chars
    ADD COLUMN approx_record_ct BIGINT,
    DROP COLUMN data_point_ct;

ALTER TABLE profiling_runs
    ADD COLUMN progress JSONB,
    ADD COLUMN record_ct BIGINT,
    ADD COLUMN data_point_ct BIGINT;

ALTER TABLE profile_results
    DROP COLUMN column_id,
    ADD COLUMN query_error VARCHAR(2000);
