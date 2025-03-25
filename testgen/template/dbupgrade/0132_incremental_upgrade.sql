SET SEARCH_PATH TO {SCHEMA_NAME};

-- Pre-populate the score_history_latest_runs table with existing profiling and test runs
DO $$
DECLARE
   current_project VARCHAR(30);
   current_definition UUID;
   cutoff_time TIMESTAMP;
BEGIN
   -- For each project
   FOR current_project IN SELECT project_code FROM projects LOOP
      -- and, for each score definition within this project
      FOR current_definition IN SELECT id FROM score_definitions WHERE project_code = current_project LOOP
         -- iterate over all existing profiling cutoff times for the project
         FOR cutoff_time IN SELECT profiling_starttime AS time_ FROM profiling_runs WHERE project_code = current_project LOOP
            -- delete existing cutoff times
            DELETE FROM score_history_latest_runs
            WHERE definition_id = current_definition
               AND score_history_cutoff_time = cutoff_time;

            -- and insert the latest profiling runs
            WITH ranked_profiling AS (
               SELECT
                  project_code,
                  table_groups_id,
                  id as profiling_run_id,
                  ROW_NUMBER() OVER (PARTITION BY table_groups_id ORDER BY profiling_starttime DESC) as rank
               FROM profiling_runs r
               WHERE project_code = current_project
                  AND profiling_starttime <= cutoff_time
                  AND r.status = 'Complete'
            )
            INSERT INTO score_history_latest_runs
               (definition_id, score_history_cutoff_time, table_groups_id, last_profiling_run_id)
            SELECT current_definition as definition_id, cutoff_time as score_history_cutoff_time, table_groups_id, profiling_run_id
            FROM ranked_profiling
            WHERE rank = 1;

            -- and insert the latest test runs
            WITH ranked_test_runs AS (
               SELECT
                  r.test_suite_id,
                  r.id as test_run_id,
                  ROW_NUMBER() OVER (PARTITION BY test_suite_id ORDER BY test_starttime DESC) as rank
               FROM test_runs r
               INNER JOIN test_suites s
                  ON (r.test_suite_id = s.id)
                  WHERE s.project_code = current_project
                  AND r.test_starttime <= cutoff_time
                  AND r.status = 'Complete'
            )
            INSERT INTO score_history_latest_runs
               (definition_id, score_history_cutoff_time, test_suite_id, last_test_run_id)
            SELECT current_definition AS definition_id, cutoff_time AS score_history_cutoff_time, test_suite_id, test_run_id
            FROM ranked_test_runs
            WHERE rank = 1;
         END LOOP;

         -- also, iterate over all existing tests cutoff times for the project
         FOR cutoff_time IN SELECT test_starttime AS time_ FROM test_runs AS tr INNER JOIN test_suites AS ts ON (ts.id = tr.test_suite_id) WHERE ts.project_code = current_project LOOP
            -- delete existing cutoff times
            DELETE FROM score_history_latest_runs
            WHERE definition_id = current_definition
               AND score_history_cutoff_time = cutoff_time;

            -- and insert the latest profiling runs
            WITH ranked_profiling AS (
               SELECT
                  project_code,
                  table_groups_id,
                  id as profiling_run_id,
                  ROW_NUMBER() OVER (PARTITION BY table_groups_id ORDER BY profiling_starttime DESC) as rank
               FROM profiling_runs r
               WHERE project_code = current_project
                  AND profiling_starttime <= cutoff_time
                  AND r.status = 'Complete'
            )
            INSERT INTO score_history_latest_runs
               (definition_id, score_history_cutoff_time, table_groups_id, last_profiling_run_id)
            SELECT current_definition as definition_id, cutoff_time as score_history_cutoff_time, table_groups_id, profiling_run_id
            FROM ranked_profiling
            WHERE rank = 1;

            -- and insert the latest test runs
            WITH ranked_test_runs AS (
               SELECT
                  r.test_suite_id,
                  r.id as test_run_id,
                  ROW_NUMBER() OVER (PARTITION BY test_suite_id ORDER BY test_starttime DESC) as rank
               FROM test_runs r
               INNER JOIN test_suites s
                  ON (r.test_suite_id = s.id)
                  WHERE s.project_code = current_project
                  AND r.test_starttime <= cutoff_time
                  AND r.status = 'Complete'
            )
            INSERT INTO score_history_latest_runs
               (definition_id, score_history_cutoff_time, test_suite_id, last_test_run_id)
            SELECT current_definition AS definition_id, cutoff_time AS score_history_cutoff_time, test_suite_id, test_run_id
            FROM ranked_test_runs
            WHERE rank = 1;
         END LOOP;
      END LOOP;
   END LOOP;
END $$;
