-- All codes / categories with few distinct values
SELECT schema_name, table_name, STRING_AGG(column_name, ',' ORDER BY column_name) as contingency_columns
  FROM profile_results p
 WHERE profile_run_id = '{PROFILE_RUN_ID}'::UUID
   AND functional_data_type IN ('Code', 'Category')
   AND distinct_value_ct BETWEEN 2 AND {CONTINGENCY_MAX_VALUES}
GROUP BY schema_name, table_name;
