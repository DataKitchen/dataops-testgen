SELECT
    '{TEST_TYPE}' AS test_type,
    '{TEST_DEFINITION_ID}' AS test_definition_id,
    '{TEST_SUITE_ID}' AS test_suite_id,
    '{TEST_RUN_ID}' AS test_run_id,
    '{RUN_DATE}' AS test_time,
    '{SCHEMA_NAME}' AS schema_name,
    '{TABLE_NAME}' AS table_name,
    '{COLUMN_NAME_NO_QUOTES}' AS column_names,
    '{SKIP_ERRORS}' AS threshold_value,
    {SKIP_ERRORS} AS skip_errors,
    '{INPUT_PARAMETERS}' AS input_parameters,
    NULL as result_signal,
    CASE WHEN COUNT(*) > {SKIP_ERRORS} THEN 0 ELSE 1 END AS result_code,
    CASE
      WHEN COUNT(*) > 0 THEN CONCAT(
        CAST(COUNT(*) AS STRING), ' error(s) identified, ',
        CASE
          WHEN COUNT(*) > {SKIP_ERRORS} THEN 'exceeding limit of '
          ELSE 'within limit of '
        END,
        '{SKIP_ERRORS}.'
      )
      ELSE 'No errors found.'
    END AS result_message,
    COUNT(*) AS result_measure
    FROM (
      SELECT {COLUMN_NAME_NO_QUOTES}
      FROM `{SCHEMA_NAME}.{TABLE_NAME}`
      WHERE {SUBSET_CONDITION}
        AND {WINDOW_DATE_COLUMN} >= DATE_SUB((SELECT MAX({WINDOW_DATE_COLUMN}) FROM `{SCHEMA_NAME}.{TABLE_NAME}`), INTERVAL 2 * {WINDOW_DAYS} DAY)
        AND {WINDOW_DATE_COLUMN} <  DATE_SUB((SELECT MAX({WINDOW_DATE_COLUMN}) FROM `{SCHEMA_NAME}.{TABLE_NAME}`), INTERVAL {WINDOW_DAYS} DAY)
      GROUP BY {COLUMN_NAME_NO_QUOTES}
      EXCEPT DISTINCT
      SELECT {COLUMN_NAME_NO_QUOTES}
      FROM `{SCHEMA_NAME}.{TABLE_NAME}`
      WHERE {SUBSET_CONDITION}
        AND {WINDOW_DATE_COLUMN} >= DATE_SUB((SELECT MAX({WINDOW_DATE_COLUMN}) FROM `{SCHEMA_NAME}.{TABLE_NAME}`), INTERVAL {WINDOW_DAYS} DAY)
      GROUP BY {COLUMN_NAME_NO_QUOTES}
    ) test;
