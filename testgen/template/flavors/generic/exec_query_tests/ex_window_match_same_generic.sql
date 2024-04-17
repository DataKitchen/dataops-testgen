SELECT '{PROJECT_CODE}' as project_code, '{TEST_TYPE}' as test_type,
       '{TEST_DEFINITION_ID}' as test_definition_id,
       '{TEST_SUITE}' as test_suite,
       '{RUN_DATE}' as test_time, '{START_TIME}' as starttime, CURRENT_TIMESTAMP as endtime,
       '{SCHEMA_NAME}' as schema_name, '{TABLE_NAME}' as table_name, '{COLUMN_NAME}' as column_names,
       {SKIP_ERRORS} as skip_errors,
       'schema_name = {SCHEMA_NAME}, table_name = {TABLE_NAME}, column_name = {COLUMN_NAME}, subset_condition = {SUBSET_CONDITION}, window_date_column = {WINDOW_DATE_COLUMN},window_days = {WINDOW_DAYS}, mode = {MODE}'
         as input_parameters,
       CASE WHEN COUNT(*) > COALESCE(skip_errors, 0) THEN 0 ELSE 1 END as result_code,
       CONCAT(
             CONCAT( 'Mismatched values: ', CAST( COALESCE(COUNT(*), 0) AS VARCHAR) ),
             CONCAT( ', Threshold: ',
                     CONCAT( CAST(COALESCE(skip_errors, 0) AS VARCHAR), '.')
                    )
              )  AS result_message,
       COUNT(*) as result_measure,
       '{TEST_ACTION}' as test_action,
       '{SUBSET_CONDITION}' as subset_condition,
       NULL as result_query,
       '{TEST_DESCRIPTION}' as test_description
  FROM (
        (
SELECT {COLUMN_NAME}
FROM {SCHEMA_NAME}.{TABLE_NAME}
WHERE {SUBSET_CONDITION}
  AND {WINDOW_DATE_COLUMN} BETWEEN (SELECT MAX({WINDOW_DATE_COLUMN}) FROM {SCHEMA_NAME}.{TABLE_NAME}) - {WINDOW_DAYS}
  AND (SELECT MAX({WINDOW_DATE_COLUMN}) FROM {SCHEMA_NAME}.{TABLE_NAME})
EXCEPT
SELECT {COLUMN_NAME}
FROM {SCHEMA_NAME}.{TABLE_NAME}
WHERE {SUBSET_CONDITION}
  AND {WINDOW_DATE_COLUMN} BETWEEN (SELECT MAX({WINDOW_DATE_COLUMN}) FROM {SCHEMA_NAME}.{TABLE_NAME}) - 2 * {WINDOW_DAYS}
  AND (SELECT MAX({WINDOW_DATE_COLUMN}) FROM {SCHEMA_NAME}.{TABLE_NAME}) - {WINDOW_DAYS}
)
UNION
(
SELECT {COLUMN_NAME}
FROM {SCHEMA_NAME}.{TABLE_NAME}
WHERE {SUBSET_CONDITION}
  AND {WINDOW_DATE_COLUMN} BETWEEN (SELECT MAX({WINDOW_DATE_COLUMN}) FROM {SCHEMA_NAME}.{TABLE_NAME}) - 2 * {WINDOW_DAYS}
  AND (SELECT MAX({WINDOW_DATE_COLUMN}) FROM {SCHEMA_NAME}.{TABLE_NAME}) - {WINDOW_DAYS}
    EXCEPT
SELECT {COLUMN_NAME}
FROM {SCHEMA_NAME}.{TABLE_NAME}
WHERE {SUBSET_CONDITION}
  AND {WINDOW_DATE_COLUMN} BETWEEN (SELECT MAX({WINDOW_DATE_COLUMN}) FROM {SCHEMA_NAME}.{TABLE_NAME}) - {WINDOW_DAYS}
  AND (SELECT MAX({WINDOW_DATE_COLUMN}) FROM {SCHEMA_NAME}.{TABLE_NAME})
)
       ) test;
