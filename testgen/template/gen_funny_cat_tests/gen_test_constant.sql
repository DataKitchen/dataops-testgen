-- Then insert new tests where a locked test is not already present

INSERT INTO test_definitions (table_groups_id, profile_run_id,
                              test_type, test_suite_id,
                              schema_name, table_name, column_name, skip_errors,
                              last_auto_gen_date, test_active,
                              baseline_value, threshold_value, profiling_as_of_date)
WITH last_run AS (SELECT r.table_groups_id, MAX(run_date) AS last_run_date
                    FROM profile_results p
                  INNER JOIN profiling_runs r
                     ON (p.profile_run_id = r.id)
                    INNER JOIN test_suites ts
                       ON p.project_code = ts.project_code
                      AND p.connection_id = ts.connection_id
                   WHERE p.project_code = '{PROJECT_CODE}'
                     AND r.table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                     AND ts.id = '{TEST_SUITE_ID}'
                     AND p.run_date::DATE <= '{AS_OF_DATE}'
                  GROUP BY r.table_groups_id),
     curprof AS (SELECT p.*
                   FROM last_run lr
                 INNER JOIN profile_results p
                    ON (lr.table_groups_id = p.table_groups_id
                    AND lr.last_run_date = p.run_date) ),
     locked AS (SELECT schema_name, table_name, column_name, test_type
                  FROM test_definitions
				     WHERE table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                   AND test_suite_id = '{TEST_SUITE_ID}'
                   AND lock_refresh = 'Y'),
     all_runs AS ( SELECT DISTINCT p.table_groups_id, p.schema_name, p.run_date,
                          DENSE_RANK() OVER (PARTITION BY p.table_groups_id ORDER BY p.run_date DESC) as run_rank
                     FROM profile_results p
                   INNER JOIN test_suites ts
                      ON p.connection_id = ts.connection_id
                     AND p.project_code = ts.project_code
                   WHERE p.table_groups_id = '{TABLE_GROUPS_ID}'::UUID
                     AND ts.id = '{TEST_SUITE_ID}'
                     AND p.run_date::DATE <= '{AS_OF_DATE}'),
     recent_runs AS (SELECT table_groups_id, schema_name, run_date, run_rank
                       FROM all_runs
                      WHERE run_rank <= 5),
     rightcols as (SELECT p.schema_name, p.table_name, p.column_name,
                          SUM(CASE WHEN distinct_value_ct = 1 THEN 0 ELSE 1 END) as always_one_val,
                          COUNT(DISTINCT CASE
                                           WHEN p.general_type = 'A' THEN min_text
                                           WHEN p.general_type = 'N' THEN min_value::VARCHAR
                                           WHEN p.general_type IN ('D','T') THEN min_date::VARCHAR
                                           WHEN p.general_type = 'B'
                                            AND boolean_true_ct = value_ct  THEN 'TRUE'
                                           WHEN p.general_type = 'B'
                                            AND p.boolean_true_ct = 0
                                            AND p.distinct_value_ct = 1     THEN 'FALSE'
                                         END ) as agg_distinct_val_ct
                    FROM recent_runs rr
                  INNER JOIN profile_results p
                     ON (rr.table_groups_id = p.table_groups_id
                    AND  rr.run_date = p.run_date)
                  GROUP BY p.schema_name, p.table_name, p.column_name
                  HAVING SUM(CASE WHEN distinct_value_ct = 1 THEN 0 ELSE 1 END) = 0
                     AND SUM(CASE WHEN max_length < 100 THEN 0 ELSE 1 END) = 0
                     AND COUNT(DISTINCT CASE
                                           WHEN p.general_type = 'A' THEN min_text
                                           WHEN p.general_type = 'N' THEN min_value::VARCHAR
                                           WHEN p.general_type IN ('D','T') THEN min_date::VARCHAR
                                           WHEN p.general_type = 'B'
                                            AND boolean_true_ct = value_ct  THEN 'TRUE'
                                           WHEN p.general_type = 'B'
                                            AND p.boolean_true_ct = 0
                                            AND p.distinct_value_ct = 1     THEN 'FALSE'
                                         END ) = 1 ),
newtests AS ( SELECT 'Constant'::VARCHAR AS test_type,
                     '{TEST_SUITE_ID}'::UUID AS test_suite_id,
                     c.profile_run_id,
                     c.schema_name, c.table_name, c.column_name,
                     c.run_date AS last_run_date,
                   case when general_type='A' then fn_quote_literal_escape(min_text, '{SQL_FLAVOR}')::VARCHAR
                        when general_type='D' then fn_quote_literal_escape(min_date :: VARCHAR, '{SQL_FLAVOR}')::VARCHAR
                        when general_type='N' then min_value::VARCHAR
                        when general_type='B' and boolean_true_ct = 0 then 'FALSE'::VARCHAR
                        when general_type='B' and boolean_true_ct > 0 then 'TRUE'::VARCHAR
                   end as baseline_value
                FROM curprof c
               INNER JOIN rightcols r
                  ON (c.schema_name = r.schema_name
                     AND c.table_name = r.table_name
                     AND c.column_name = r.column_name)
               LEFT JOIN generation_sets s
                  ON ('Constant' = s.test_type
                 AND  '{GENERATION_SET}' = s.generation_set)
               WHERE (s.generation_set IS NOT NULL
                  OR  '{GENERATION_SET}' = '')  )
SELECT '{TABLE_GROUPS_ID}'::UUID as table_groups_id, n.profile_run_id,
       n.test_type, n.test_suite_id, n.schema_name, n.table_name, n.column_name,
       0 as skip_errors, '{RUN_DATE}'::TIMESTAMP as auto_gen_date,
       'Y' as test_active, COALESCE(baseline_value, '') as baseline_value,
       '0' as threshold_value, '{AS_OF_DATE}'::TIMESTAMP
  FROM newtests n
LEFT JOIN locked l
  ON (n.schema_name = l.schema_name
 AND  n.table_name = l.table_name
 AND  n.column_name = l.column_name
 AND  n.test_type = l.test_type)
 WHERE l.test_type IS NULL;
