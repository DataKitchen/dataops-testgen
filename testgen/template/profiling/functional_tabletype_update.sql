UPDATE profile_results
   SET functional_table_type = COALESCE(s.table_period)||'-'||COALESCE(s.table_type)
FROM stg_functional_table_updates s
WHERE s.project_code = profile_results.project_code
  AND s.schema_name = profile_results.schema_name
  AND s.table_name = profile_results.table_name
  AND s.run_date = profile_results.run_date
  AND s.run_date = '{RUN_DATE}';
