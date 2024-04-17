SELECT tt.test_type,
       s.id::VARCHAR as test_definition_id,
       COALESCE(s.test_description, tt.test_description) as test_description,
       COALESCE(s.test_action, g.test_action, '')      as test_action,
       schema_name,
       table_name,
       column_name,
       cast(coalesce(skip_errors, 0) as varchar(50))   as skip_errors,
       coalesce(baseline_ct, '')                       as baseline_ct,
       coalesce(baseline_unique_ct, '')                as baseline_unique_ct,
       coalesce(baseline_value, '')                    as baseline_value,
       coalesce(baseline_value_ct, '')                 as baseline_value_ct,
       coalesce(threshold_value, '')                   as threshold_value,
       coalesce(baseline_sum, '')                      as baseline_sum,
       coalesce(baseline_avg, '')                      as baseline_avg,
       coalesce(baseline_sd, '')                       as baseline_sd,
       case
           when nullif(subset_condition, '') is null then '1=1'
           else subset_condition end                   as subset_condition,
       coalesce(groupby_names, '')                     as groupby_names,
       case
           when having_condition is null then ''
           else concat('WHERE ', having_condition) end as having_condition,
       coalesce(window_date_column, '')                as window_date_column,
       cast(coalesce(window_days, '0') as varchar(50)) as window_days,
       coalesce(match_schema_name, '')                 as match_schema_name,
       coalesce(match_table_name, '')                  as match_table_name,
       coalesce(match_column_names, '')                as match_column_names,
       case
           when nullif(match_subset_condition, '') is null then '1=1'
           else match_subset_condition end             as match_subset_condition,
       coalesce(match_groupby_names, '')               as match_groupby_names,
       coalesce(match_having_condition, '')            as match_having_condition,
       coalesce(custom_query, '')                      as custom_query,
       coalesce(tm.template_name, '')                  as template_name
FROM test_definitions s
         INNER JOIN test_suites g
                    ON (s.test_suite = g.test_suite)
         INNER JOIN test_types tt
                    ON (s.test_type = tt.test_type)
         LEFT JOIN test_templates tm
                    ON (s.test_type = tm.test_type
                   AND  '{SQL_FLAVOR}' = tm.sql_flavor)
WHERE s.project_code = '{PROJECT_CODE}'
  AND s.test_suite = '{TEST_SUITE}'
  AND tt.run_type = 'QUERY'
  AND s.test_active = 'Y';
