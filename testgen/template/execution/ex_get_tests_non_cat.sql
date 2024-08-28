SELECT tt.test_type,
       td.id::VARCHAR                                       AS test_definition_id,
       COALESCE(td.test_description, tt.test_description)   AS test_description,
       COALESCE(td.test_action, ts.test_action, '')         AS test_action,
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
FROM test_definitions td
         INNER JOIN test_suites ts
                    ON (td.test_suite_id = ts.id)
         INNER JOIN test_types tt
                    ON (td.test_type = tt.test_type)
         LEFT JOIN test_templates tm
                    ON (td.test_type = tm.test_type
                   AND  '{SQL_FLAVOR}' = tm.sql_flavor)
WHERE td.test_suite_id = '{TEST_SUITE_ID}'
  AND tt.run_type = 'QUERY'
  AND td.test_active = 'Y';
