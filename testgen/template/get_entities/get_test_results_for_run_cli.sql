SELECT ts.test_suite as test_suite_key,
       table_name,
       column_names as column_name,
       r.test_type,
       CASE
         WHEN result_code = 1 THEN 'Passed'
         WHEN result_code = 0 AND r.severity = 'Warning' THEN 'Warning'
         WHEN result_code = 0 AND r.severity = 'Fail' THEN 'Failed'
       END as result,
       COALESCE(r.result_message, '') as result_message,
       result_measure,
       tt.measure_uom
  FROM test_results r
INNER JOIN test_types tt ON r.test_type = tt.test_type
INNER JOIN test_suites ts ON r.test_suite_id = ts.id
 WHERE test_run_id = :TEST_RUN_ID
       {ERRORS_ONLY}
ORDER BY r.schema_name, r.table_name, r.column_names, r.test_type;
