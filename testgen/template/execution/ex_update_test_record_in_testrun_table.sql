WITH stats
   AS ( SELECT r.id as test_run_id,
               COALESCE(COUNT(tr.id)                      , 0)                     AS test_ct,
               SUM(result_code)                                                    AS passed_ct,
               COALESCE(SUM(CASE WHEN tr.result_status = 'Failed' THEN 1 END), 0)  AS failed_ct,
               COALESCE(SUM(CASE WHEN tr.result_status = 'Warning' THEN 1 END), 0) AS warning_ct,
               COALESCE(SUM(CASE WHEN tr.result_message ILIKE 'ERROR%' THEN 1 ELSE 0 END), 0) AS error_ct
          FROM test_runs r
        INNER JOIN test_results tr
                ON r.id = tr.test_run_id
         WHERE r.id = '{TEST_RUN_ID}'::UUID
        GROUP BY r.id )
UPDATE test_runs
   SET status = CASE WHEN length('{EXCEPTION_MESSAGE}') = 0 then 'Complete' else 'Error' end,
       test_endtime = '{NOW}',
       log_message = '{EXCEPTION_MESSAGE}',
       duration = TO_CHAR('{NOW}' - r.test_starttime, 'HH24:MI:SS'),
       test_ct = s.test_ct,
       passed_ct = s.passed_ct,
       failed_ct = s.failed_ct,
       warning_ct = s.warning_ct,
       error_ct = s.error_ct
  FROM test_runs r
LEFT JOIN stats s
   ON r.id = s.test_run_id
WHERE r.id = '{TEST_RUN_ID}'::UUID
  AND r.id = test_runs.id;
