SELECT
	ts.id as test_suite_id,
	ts.project_code as project_key,
	ts.test_suite as test_suite_key,
	ts.connection_id,
	ts.test_suite_description,
	MAX(tr.test_starttime) as last_run
FROM test_suites ts
LEFT JOIN test_runs tr
   ON ts.project_code = tr.project_code
  AND ts.test_suite = tr.test_suite
WHERE ts.project_code = '{PROJECT_CODE}'
GROUP BY ts.id,
	ts.project_code,
	ts.test_suite,
	ts.connection_id,
	ts.test_suite_description
ORDER BY ts.test_suite;
