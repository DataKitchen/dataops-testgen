/*test-run-list: project-code, test-suite
Output: list of test runs performed for a test_suite
Alternative: project-code, table-name
Optional: table-name, column-name, from-date, thru-date*/

    SELECT ts.test_suite as test_suite_key,
           tr.test_starttime as test_time,
           tr.status,
           tr.id::VARCHAR as test_run_id,
           COUNT(DISTINCT lower(r.schema_name || '.' || table_name)) as table_ct,
           COUNT(*) as result_ct,
           SUM(CASE WHEN r.result_code = 0 THEN 1 END) as fail_ct,
           SUM(CASE WHEN r.observability_status = 'Sent' THEN 1 END) as sent_to_obs,
           process_id
      FROM test_runs tr
INNER JOIN test_results r ON tr.id = r.test_run_id
INNER JOIN test_suites ts ON tr.test_suite_id = ts.id
     WHERE ts.project_code = '{PROJECT_CODE}'
       AND ts.test_suite = '{TEST_SUITE}'
  GROUP BY tr.id,
           ts.project_code,
           ts.test_suite,
           tr.test_starttime,
           tr.status;
