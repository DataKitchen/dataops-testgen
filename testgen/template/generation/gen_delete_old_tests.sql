DELETE FROM test_definitions
 WHERE id IN (
   SELECT d.id
     FROM test_definitions d
   INNER JOIN test_types t
      ON (d.test_type = t.test_type
     AND  'CAT' = t.run_type)
   WHERE d.table_groups_id = '{TABLE_GROUPS_ID}'::UUID
     AND d.test_suite = '{TEST_SUITE}'
     AND t.selection_criteria IS NOT NULL
     AND COALESCE(d.lock_refresh, 'N') <> 'Y' );
