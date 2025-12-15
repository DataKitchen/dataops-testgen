WITH prev_test AS (
      SELECT MAX(test_time) as last_run_time
      from {APP_SCHEMA_NAME}.test_results
      where test_definition_id = '{TEST_DEFINITION_ID}'
),
change_counts AS (
      SELECT COUNT(*) FILTER (WHERE dsl.change = 'A') AS schema_adds,
      COUNT(*) FILTER (WHERE dsl.change = 'D') AS schema_drops,
      COUNT(*) FILTER (WHERE dsl.change = 'M') AS schema_mods
      FROM prev_test, {APP_SCHEMA_NAME}.data_structure_log dsl
      LEFT JOIN {APP_SCHEMA_NAME}.data_column_chars dcc ON dcc.column_id = dsl.element_id
      WHERE dcc.table_groups_id = '{TABLE_GROUPS_ID}'
      -- if no previous tests, this comparision yelds null and nothing is counted.
      AND change_date > prev_test.last_run_time
)
SELECT '{TEST_TYPE}'   AS test_type,
       '{TEST_DEFINITION_ID}' AS test_definition_id,
       '{TEST_SUITE_ID}' AS test_suite_id,
       '{TEST_RUN_ID}' AS test_run_id,
       '{RUN_DATE}'    AS test_time,
       '1' AS threshold_value,
       1 AS skip_errors,
       '{INPUT_PARAMETERS}' AS input_parameters,
       schema_adds::VARCHAR || '|' || schema_mods::VARCHAR || '|' || schema_drops::VARCHAR AS result_signal,
       CASE WHEN schema_adds+schema_mods+schema_drops > 0 THEN 0 ELSE 1 END AS result_code,
       CASE WHEN schema_adds+schema_mods+schema_drops > 0 THEN
            'Table schema changes detected'
            ELSE 'No table schema changes found.'
            END AS result_message,
       schema_adds+schema_mods+schema_drops AS result_measure
FROM change_counts
