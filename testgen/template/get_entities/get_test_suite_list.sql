    SELECT ts.id as test_suite_id,
           ts.project_code as project_key,
           ts.test_suite as test_suite_key,
           ts.connection_id,
           ts.test_suite_description,
           MAX(tr.test_starttime) as last_run
      FROM test_suites ts
 LEFT JOIN test_runs tr
        ON tr.test_suite_id = ts.id
     WHERE ts.project_code = '{PROJECT_CODE}'
  ORDER BY ts.test_suite;
