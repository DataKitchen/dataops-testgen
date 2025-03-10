-- Delete existing records for the combo of definition_id and cutoff
DELETE FROM score_history_latest_runs
WHERE definition_id = '{definition_id}'
  AND score_history_cutoff_time = '{score_history_cutoff_time}';

-- Insert latest profiling runs as of cutoff
WITH ranked_profiling
 AS (SELECT project_code, table_groups_id, id as profiling_run_id,
            ROW_NUMBER() OVER (PARTITION BY table_groups_id ORDER BY profiling_starttime DESC) as rank
      FROM profiling_runs r
     WHERE project_code = '{project_code}'
       AND profiling_starttime <= '{score_history_cutoff_time}'
       AND r.status = 'Complete')
INSERT INTO score_history_latest_runs
       (definition_id, score_history_cutoff_time, table_groups_id, last_profiling_run_id)
SELECT '{definition_id}' as definition_id, '{score_history_cutoff_time}' as score_history_cutoff_time, table_groups_id, profiling_run_id
  FROM ranked_profiling
 WHERE rank = 1;
