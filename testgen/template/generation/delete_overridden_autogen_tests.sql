DELETE FROM test_definitions g
WHERE g.test_suite_id = :TEST_SUITE_ID ::UUID
  -- Only this run's auto-generated tests (never manual NULL, never prior runs)
  AND g.last_auto_gen_date = :RUN_DATE
  -- Never touch locked/manual tests
  AND g.lock_refresh = 'N'
  -- An overriding auto-generated test exists on the same column this run
  AND EXISTS (
    SELECT 1 FROM test_definitions s
    JOIN test_types tt ON tt.test_type = s.test_type
    WHERE tt.overrides = g.test_type
      AND s.test_suite_id = g.test_suite_id
      AND s.schema_name   = g.schema_name
      AND s.table_name    = g.table_name
      AND s.column_name   = g.column_name
      AND s.last_auto_gen_date = :RUN_DATE
  );
