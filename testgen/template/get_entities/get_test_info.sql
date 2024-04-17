/*test-info: project-code, test-suite
Output: current detail of tests to perform for all columns within the test-suite
Alternative: project-code, connection-id
Optional: last_auto_run_date (==test-gen-run-id==), schema-name, table-name, column-name*/

SELECT s.project_code as project_key,
       s.cat_test_id,
       s.test_suite as test_suite_key,
       s.test_type,
       COALESCE(s.test_description, tt.test_description) as test_description,
       CASE
           WHEN COALESCE(s.lock_refresh, 'N') = 'N' THEN 'Allowed'
           ELSE 'Locked'
           END                                           as test_refresh,
       CASE
           WHEN COALESCE(s.test_active, 'Y') = 'N' THEN 'Disabled'
           ELSE 'Enabled'
           END                                           as disabled,
       COALESCE(s.watch_level, 'Warn')                   as watch_level,
       s.schema_name,
       s.table_name,
       s.column_name,
       tt.measure_uom,
       s.threshold_value,
       s.baseline_ct,
       s.baseline_unique_ct,
       s.baseline_value,
       s.baseline_value_ct,
       s.baseline_sum,
       s.baseline_avg,
       s.baseline_sd,
       s.subset_condition,
       s.check_result,
       s.last_auto_gen_date,
       s.profiling_as_of_date
FROM test_definitions s
         INNER JOIN test_types tt ON s.test_type = tt.test_type
WHERE s.project_code = '{PROJECT_CODE}'
  AND s.test_suite = '{TEST_SUITE}'
ORDER BY s.schema_name, s.table_name,
         s.column_name, s.test_type;
