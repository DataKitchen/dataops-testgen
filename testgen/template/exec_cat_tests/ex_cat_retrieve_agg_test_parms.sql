SELECT schema_name,
       table_name,
       cat_sequence,
       -- Replace list delimiters with concat operator
       REPLACE(test_measures, '++', '{CONCAT_OPERATOR}') as test_measures,
       REPLACE(test_conditions, '++', '{CONCAT_OPERATOR}') as test_conditions
  FROM working_agg_cat_tests
 WHERE test_run_id = '{TEST_RUN_ID}';
