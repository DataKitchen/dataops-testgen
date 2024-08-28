SELECT '{TEST_RUN_ID}' as test_run_id,
       '{SCHEMA_NAME}' as schema_name,
       '{TABLE_NAME}' as table_name,
       '{CAT_SEQUENCE}' as cat_sequence,
       {TEST_MEASURES} as measure_results,
       {TEST_CONDITIONS} as test_results
  FROM {SCHEMA_NAME}.{TABLE_NAME}
