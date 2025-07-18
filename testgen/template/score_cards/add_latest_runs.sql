-- Insert latest profiling runs as of cutoff
WITH ranked_profiling
 AS (SELECT project_code, table_groups_id, id as profiling_run_id,
            ROW_NUMBER() OVER (PARTITION BY table_groups_id ORDER BY profiling_starttime DESC) as rank
      FROM profiling_runs r
     WHERE project_code = :project_code
       AND profiling_starttime <= :score_history_cutoff_time
       AND r.status = 'Complete')
INSERT INTO score_history_latest_runs
       (definition_id, score_history_cutoff_time, table_groups_id, last_profiling_run_id)
SELECT :definition_id as definition_id, :score_history_cutoff_time as score_history_cutoff_time, table_groups_id, profiling_run_id
  FROM ranked_profiling
 WHERE rank = 1;

-- Insert latest test runs  of cutoff
WITH ranked_test_runs
 AS (SELECT r.test_suite_id,
            r.id as test_run_id,
            ROW_NUMBER() OVER (PARTITION BY test_suite_id ORDER BY test_starttime DESC) as rank
       FROM test_runs r
     INNER JOIN test_suites s
        ON (r.test_suite_id = s.id)
      WHERE s.project_code = :project_code
        AND r.test_starttime <= :score_history_cutoff_time
        AND r.status = 'Complete')
INSERT INTO score_history_latest_runs
       (definition_id, score_history_cutoff_time, test_suite_id, last_test_run_id)
SELECT :definition_id as definition_id, :score_history_cutoff_time as score_history_cutoff_time, test_suite_id, test_run_id
      FROM ranked_test_runs
     WHERE rank = 1;
