/*test-run-list: project-code, test-suite
Output: list of test runs performed for a test_suite
Alternative: project-code, table-name
Optional: table-name, column-name, from-date, thru-date*/

Select tr.test_suite as test_suite_key,
       tr.test_starttime as test_time,
       tr.status,
       tr.id::VARCHAR(50) as test_run_id,
       COUNT(DISTINCT lower(r.schema_name || '.' || table_name)) as table_ct,
       COUNT(*) as result_ct,
       SUM(CASE WHEN r.result_code = 0 THEN 1 END) as fail_ct,
       SUM(CASE WHEN r.observability_status = 'Sent' THEN 1 END) as sent_to_obs,
       process_id
from test_runs tr
INNER JOIN test_results r
   ON (tr.id = r.test_run_id)
where tr.project_code = '{PROJECT_CODE}'
and tr.test_suite = '{TEST_SUITE}'
GROUP BY tr.project_code,
       tr.test_suite,
       tr.test_starttime,
       tr.status,
       tr.id;
