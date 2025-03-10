SET SEARCH_PATH TO {SCHEMA_NAME};

-- Delete existing records for the combo of definition_id and cutoff
DELETE FROM score_history_latest_runs
WHERE definition_id = '{definition_id}'
  AND score_history_cutoff_time = '{score_history_cutoff_time}';

-- Insert latest test runs  of cutoff
WITH ranked_test_runs
 AS (SELECT r.test_suite_id,
            r.id as test_run_id,
            ROW_NUMBER() OVER (PARTITION BY test_suite_id ORDER BY test_starttime DESC) as rank
       FROM test_runs r
     INNER JOIN test_suites s
        ON (r.test_suite_id = s.id)
      WHERE s.project_code = '{project_code}'
        AND r.test_starttime <= '{score_history_cutoff_time}'
        AND r.status = 'Complete')
INSERT INTO score_history_latest_runs
       (definition_id, score_history_cutoff_time, test_suite_id, last_test_run_id)
SELECT '{definition_id}' as definition_id, '{score_history_cutoff_time}' as score_history_cutoff_time, test_suite_id, test_run_id
      FROM ranked_test_runs
     WHERE rank = 1;
