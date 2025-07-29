WITH last_run
   AS (SELECT test_suite_id, MAX(test_starttime) as max_starttime
         FROM test_runs
        WHERE test_suite_id = :TEST_SUITE_ID
          AND status = 'Complete'
       GROUP BY test_suite_id)
UPDATE test_suites
   SET last_complete_test_run_id = r.id
  FROM test_runs r
INNER JOIN last_run l
   ON (r.test_suite_id = l.test_suite_id
  AND  r.test_starttime = l.max_starttime)
 WHERE test_suites.id = r.test_suite_id;