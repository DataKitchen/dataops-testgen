DELETE FROM test_definitions
 WHERE table_groups_id = '{TABLE_GROUPS_ID}'::UUID
   AND test_suite_id = '{TEST_SUITE_ID}'
   AND last_auto_gen_date IS NOT NULL
   AND COALESCE(lock_refresh, 'N') <> 'Y';
