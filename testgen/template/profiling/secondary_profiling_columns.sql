-- Looking for columns not already freq'd,
-- but with max_length * distinct_value_ct that fit in result
SELECT schema_name,
       table_name,
       column_name
  FROM profile_results p
 WHERE p.project_code = '{PROJECT_CODE}'
   AND p.schema_name = '{DATA_SCHEMA}'
   AND p.run_date = '{RUN_DATE}'
   AND p.top_freq_values IS NULL
   AND p.general_type = 'A'
   AND p.distinct_value_ct BETWEEN 2 and 40
   AND p.max_length <= 70
/*
   AND 10 * (p.max_length + 15) < 1200
 */
 ;
