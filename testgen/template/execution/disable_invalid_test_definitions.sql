UPDATE test_definitions td
SET test_active = 'N',
  test_definition_status = LEFT('Deactivated ' || :RUN_DATE || ': ' || tr.result_message, 200)
FROM test_results tr
WHERE td.id = tr.test_definition_id
  AND tr.test_run_id = :TEST_RUN_ID;
