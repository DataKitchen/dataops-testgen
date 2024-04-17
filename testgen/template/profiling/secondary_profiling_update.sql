UPDATE profile_results
   SET top_freq_values = u.top_freq_values,
       distinct_value_hash = u.distinct_value_hash
  FROM profile_results p
INNER JOIN stg_secondary_profile_updates u
   ON p.project_code = u.project_code
  AND p.schema_name = u.schema_name
  AND p.run_date = u.run_date
  AND p.table_name = u.table_name
  AND p.column_name = u.column_name
WHERE p.project_code = profile_results.project_code
  AND p.schema_name = profile_results.schema_name
  AND p.run_date = profile_results.run_date
  AND p.table_name = profile_results.table_name
  AND p.column_name = profile_results.column_name
  AND p.project_code = '{PROJECT_CODE}'
   AND p.schema_name = '{DATA_SCHEMA}'
   AND p.run_date = '{RUN_DATE}';
