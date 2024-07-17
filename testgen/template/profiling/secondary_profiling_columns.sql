-- Looking for columns not already freq'd,
-- but with max_length * distinct_value_ct that fit in result
SELECT schema_name,
       table_name,
       column_name
  FROM profile_results p
 WHERE p.profile_run_id = '{PROFILE_RUN_ID}'
   AND p.top_freq_values IS NULL
   AND p.general_type = 'A'
   AND p.distinct_value_ct BETWEEN 2 and 70
   AND p.max_length <= 70
;
