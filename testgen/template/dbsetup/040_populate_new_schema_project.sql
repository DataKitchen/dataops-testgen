SET SEARCH_PATH TO {SCHEMA_NAME};

INSERT INTO projects
    (project_code, project_name, effective_from_date, observability_api_key, observability_api_url)
SELECT '{PROJECT_CODE}' as project_code,
       '{PROJECT_NAME}' as project_name,
       (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::DATE      as effective_from_date,
       '{OBSERVABILITY_API_KEY}' as observability_api_key,
       '{OBSERVABILITY_API_URL}' as observability_api_url;

INSERT INTO connections
(project_code, sql_flavor,
 project_host, project_port, project_user, project_db, project_qc_schema,
 connection_name, project_pw_encrypted, max_threads, max_query_chars)
SELECT '{PROJECT_CODE}'                       as project_code,
       '{SQL_FLAVOR}'                         as sql_flavor,
       '{PROJECT_HOST}'                       as project_host,
       '{PROJECT_PORT}'                       as project_port,
       '{PROJECT_USER}'                       as project_user,
       '{PROJECT_DB}'                         as project_db,
       '{PROJECT_QC_SCHEMA}'                  as project_qc_schema,
       '{CONNECTION_NAME}'                    as connection_name,
       '{PROJECT_PW_ENCRYPTED}'               as project_pw_encrypted,
       '{MAX_THREADS}'::INTEGER               as max_threads,
       '{MAX_QUERY_CHARS}'::INTEGER           as max_query_chars;

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
        15000 as profile_sample_min_count;

INSERT INTO test_suites
   (project_code, test_suite, connection_id, table_groups_id, test_suite_description,
    export_to_observability, component_key, component_type)
SELECT '{PROJECT_CODE}'     as project_code,
       '{TEST_SUITE}'       as test_suite,
       1                    as connection_id,
       '0ea85e17-acbe-47fe-8394-9970725ad37d'::UUID as table_groups_id,
       '{TEST_SUITE} Test Suite' as test_suite_description,
       'Y' as export_to_observability,
	   NULL as component_key,
	   '{OBSERVABILITY_COMPONENT_TYPE}' as component_type;

INSERT INTO auth_users
    (username, email, name, password, role)
SELECT
    '{UI_USER_USERNAME}' as username,
    '{UI_USER_EMAIL}' as email,
    '{UI_USER_NAME}' as name,
    '{UI_USER_ENCRYPTED_PASSWORD}' as password,
    'admin' as role;
