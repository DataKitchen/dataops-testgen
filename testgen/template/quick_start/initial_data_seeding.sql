SET SEARCH_PATH TO {SCHEMA_NAME};

INSERT INTO connections
(project_code, sql_flavor, sql_flavor_code,
 project_host, project_port, project_user, project_db,
 connection_name, project_pw_encrypted, http_path, max_threads, max_query_chars)
SELECT '{PROJECT_CODE}'                            as project_code,
       '{SQL_FLAVOR}'                              as sql_flavor,
       '{SQL_FLAVOR}'                              as sql_flavor_code,
       NULLIF('{PROJECT_HOST}', '')                as project_host,
       NULLIF('{PROJECT_PORT}', '')                as project_port,
       NULLIF('{PROJECT_USER}', '')                as project_user,
       NULLIF('{PROJECT_DB}', '')                  as project_db,
       '{CONNECTION_NAME}'                         as connection_name,
       NULLIF('{PROJECT_PW_ENCRYPTED}', ''::BYTEA) as project_pw_encrypted,
       NULLIF('{PROJECT_HTTP_PATH}', '')           as http_path,
       '{MAX_THREADS}'::INTEGER                    as max_threads,
       '{MAX_QUERY_CHARS}'::INTEGER                as max_query_chars;

INSERT INTO table_groups
(id, project_code, connection_id, table_groups_name, table_group_schema, profiling_table_set, profiling_include_mask, profiling_exclude_mask,
 profile_sample_min_count)
SELECT '0ea85e17-acbe-47fe-8394-9970725ad37d'::UUID as id,
       '{PROJECT_CODE}'                         as project_code,
       1                                        as connection_id,
       '{TABLE_GROUPS_NAME}'                    as table_groups_name,
       '{PROJECT_SCHEMA}'                       as table_group_schema,
       NULLIF('{PROFILING_TABLE_SET}', '')      as profiling_table_set,
       NULLIF('{PROFILING_INCLUDE_MASK}', '')   as profiling_include_mask,
       NULLIF('{PROFILING_EXCLUDE_MASK}', '')   as profiling_exclude_mask,
       15000                                    as profile_sample_min_count;

INSERT INTO test_suites
   (id, project_code, test_suite, connection_id, table_groups_id, test_suite_description,
    export_to_observability, component_key, component_type)
SELECT '9df7489d-92b3-49f9-95ca-512160d7896f'::UUID as id,
       '{PROJECT_CODE}'     as project_code,
       '{TEST_SUITE}'       as test_suite,
       1                    as connection_id,
       '0ea85e17-acbe-47fe-8394-9970725ad37d'::UUID as table_groups_id,
       '{TEST_SUITE} Test Suite' as test_suite_description,
       'Y' as export_to_observability,
	   NULL as component_key,
	   '{OBSERVABILITY_COMPONENT_TYPE}' as component_type;

INSERT INTO test_suites
   (id, project_code, test_suite, connection_id, table_groups_id, test_suite_description,
    export_to_observability, is_monitor, monitor_lookback, predict_min_lookback)
SELECT '823a1fef-9b6d-48d5-9d0f-2db9812cc318'::UUID AS id,
       '{PROJECT_CODE}'                             AS project_code,
       '{TABLE_GROUPS_NAME} Monitors'               AS test_suite,
       1                                            AS connection_id,
       '0ea85e17-acbe-47fe-8394-9970725ad37d'::UUID AS table_groups_id,
       '{TABLE_GROUPS_NAME} Monitor Suite'          AS test_suite_description,
       'N'                                          AS export_to_observability,
       TRUE                                         AS is_monitor,
       28                                           AS monitor_lookback,
       30                                           AS predict_min_lookback;

INSERT INTO job_schedules
    (id, project_code, key, args, kwargs, cron_expr, cron_tz, active)
SELECT 'eac9d722-d06a-4b1f-b8c4-bb2854bd4cfd'::UUID AS id,
       '{PROJECT_CODE}'                             AS project_code,
       'run-monitors'                               AS key,
       '[]'::JSONB                                  AS args,
       '{"test_suite_id": "823a1fef-9b6d-48d5-9d0f-2db9812cc318"}'::JSONB AS kwargs,
       '0 */12 * * *'                               AS cron_expr,
       'UTC'                                        AS cron_tz,
       TRUE                                         AS TRUE;

UPDATE table_groups
SET monitor_test_suite_id = '823a1fef-9b6d-48d5-9d0f-2db9812cc318'::UUID
WHERE id = '0ea85e17-acbe-47fe-8394-9970725ad37d'::UUID;

-- Metric monitors
INSERT INTO test_definitions
    (id, table_groups_id, test_suite_id, test_type, schema_name, table_name, column_name,
     custom_query, history_calculation, history_calculation_upper, lower_tolerance, upper_tolerance, test_active)
VALUES
    -- Average Discount
    ('a1b2c3d4-1006-4000-8000-000000000006'::UUID,
     '0ea85e17-acbe-47fe-8394-9970725ad37d'::UUID,
     '823a1fef-9b6d-48d5-9d0f-2db9812cc318'::UUID,
     'Metric_Trend', '{PROJECT_SCHEMA}', 'f_ebike_sales', 'Average Discount',
     'AVG(discount_amount)', NULL, NULL, 15, 25, 'Y'),

    -- Average Product Price
    ('a1b2c3d4-3333-4000-8000-000000000003'::UUID,
     '0ea85e17-acbe-47fe-8394-9970725ad37d'::UUID,
     '823a1fef-9b6d-48d5-9d0f-2db9812cc318'::UUID,
     'Metric_Trend', '{PROJECT_SCHEMA}', 'd_ebike_products', 'Average Product Price',
     'AVG(price)', NULL, NULL, 1000, 1500, 'Y'),

    -- Max Discount
    ('a1b2c3d4-2006-4000-8000-000000000006'::UUID,
     '0ea85e17-acbe-47fe-8394-9970725ad37d'::UUID,
     '823a1fef-9b6d-48d5-9d0f-2db9812cc318'::UUID,
     'Metric_Trend', '{PROJECT_SCHEMA}', 'd_ebike_products', 'Max Discount',
     'MAX(max_discount)', 'PREDICT', NULL, NULL, NULL, 'Y');
