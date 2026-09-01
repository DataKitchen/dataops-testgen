-- Looking for columns with max_length * distinct_value_ct that fit in result.
-- Eligibility depends only on what the column pass measured, so the list is the same every
-- time it is asked for; a run that continues skips what it already wrote by its own account.
SELECT schema_name,
       table_name,
       column_name
  FROM profile_results p
 WHERE p.profile_run_id = :PROFILE_RUN_ID
   AND p.general_type = 'A'
   AND p.distinct_value_ct BETWEEN 2 and 70
   AND p.max_length <= 70
;
