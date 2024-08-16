/*test-info: project-code, test-suite
Output: current detail of tests to perform for all columns within the test-suite
Alternative: project-code, connection-id
Optional: last_auto_run_date (==test-gen-run-id==), schema-name, table-name, column-name*/

    SELECT ts.project_code as project_key,
           td.cat_test_id,
           ts.test_suite as test_suite_key,
           td.test_type,
           COALESCE(td.test_description, tt.test_description) as test_description,
           CASE
               WHEN COALESCE(td.lock_refresh, 'N') = 'N' THEN 'Allowed'
               ELSE 'Locked'
               END                                           as test_refresh,
           CASE
               WHEN COALESCE(td.test_active, 'Y') = 'N' THEN 'Disabled'
               ELSE 'Enabled'
               END                                           as disabled,
           COALESCE(td.watch_level, 'Warn')                   as watch_level,
           td.schema_name,
           td.table_name,
           td.column_name,
           tt.measure_uom,
           td.threshold_value,
           td.baseline_ct,
           td.baseline_unique_ct,
           td.baseline_value,
           td.baseline_value_ct,
           td.baseline_sum,
           td.baseline_avg,
           td.baseline_sd,
           td.subset_condition,
           td.check_result,
           td.last_auto_gen_date,
           td.profiling_as_of_date
      FROM test_definitions td
INNER JOIN test_types tt ON td.test_type = tt.test_type
INNER JOIN test_suites ts ON td.test_suite_id = ts.id
     WHERE ts.project_code = '{PROJECT_CODE}'
       AND ts.test_suite = '{TEST_SUITE}'
  ORDER BY td.schema_name,
           td.table_name,
           td.column_name,
           td.test_type;
