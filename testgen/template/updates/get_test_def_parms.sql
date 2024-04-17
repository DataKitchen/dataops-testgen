SELECT td.project_code, td.test_suite,
       td.schema_name, td.table_name, td.column_name,
       td.id::VARCHAR(50), td.test_type,
       CASE WHEN td.test_description IS NOT NULL THEN td.test_description ELSE tt.test_description END
           as test_description,
       td.test_action,
       td.test_active,
       td.lock_refresh,
       td.severity,
       tt.default_parm_columns  as test_parameters,
       td.baseline_ct,
       td.baseline_unique_ct,
       td.baseline_value,
       td.baseline_value_ct,
       td.threshold_value,
       td.baseline_sum,
       td.baseline_avg,
       td.baseline_sd,
       td.subset_condition,
       td.groupby_names,
       td.having_condition,
       td.window_date_column,
       td.window_days,
       td.match_schema_name,
       td.match_table_name,
       td.match_column_names,
       td.match_subset_condition,
       td.match_groupby_names,
       td.match_having_condition,
       td.custom_query

FROM test_definitions td
         INNER JOIN test_types tt
                    ON (td.test_type = tt.test_type)
WHERE project_code = '{PROJECT_CODE}'
  AND test_suite = '{TEST_SUITE}'
ORDER BY td.project_code, td.test_suite,
         td.schema_name, td.table_name, td.column_name, td.test_type;
