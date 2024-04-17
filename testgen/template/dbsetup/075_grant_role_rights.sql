-- ==============================================================================
-- |   Assigns Standard Rights to Roles:
-- |      Runs on schema create or upgrade.
-- |      No new objects should be created in this script.
-- ==============================================================================

-- testgen_execute_role:
--     read-write to test_results, test_suites, test_definitions
--     read-only to all other tables
GRANT USAGE ON SCHEMA {SCHEMA_NAME} TO testgen_execute_role;
GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA_NAME} TO testgen_execute_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA_NAME} TO testgen_execute_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {SCHEMA_NAME} TO testgen_execute_role;
GRANT SELECT, INSERT, DELETE, UPDATE ON
    {SCHEMA_NAME}.test_results,
    {SCHEMA_NAME}.test_suites,
    {SCHEMA_NAME}.test_definitions,
    {SCHEMA_NAME}.profiling_runs,
    {SCHEMA_NAME}.profile_results,
    {SCHEMA_NAME}.profile_pair_rules,
    {SCHEMA_NAME}.profile_anomaly_results,
    {SCHEMA_NAME}.stg_functional_table_updates,
    {SCHEMA_NAME}.stg_secondary_profile_updates,
    {SCHEMA_NAME}.test_runs,
    {SCHEMA_NAME}.working_agg_cat_results,
    {SCHEMA_NAME}.working_agg_cat_tests,
    {SCHEMA_NAME}.functional_test_results,
    {SCHEMA_NAME}.connections,
    {SCHEMA_NAME}.table_groups,
    {SCHEMA_NAME}.projects,
    {SCHEMA_NAME}.data_table_chars,
    {SCHEMA_NAME}.data_column_chars,
    {SCHEMA_NAME}.auth_users
    TO testgen_execute_role;



-- testgen_report_role:
--     read-only to all data
GRANT USAGE ON SCHEMA {SCHEMA_NAME} TO testgen_report_role;
GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA_NAME} TO testgen_report_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA_NAME} TO testgen_report_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {SCHEMA_NAME} TO testgen_report_role;
