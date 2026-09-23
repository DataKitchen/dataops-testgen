UPDATE test_definitions td
SET test_active = 'N',
  test_definition_status = LEFT('Deactivated ' || :RUN_DATE || '.' || SUBSTRING(tr.result_message, 13), 200)
FROM test_results tr
  INNER JOIN test_suites ts ON ts.id = tr.test_suite_id
WHERE td.id = tr.test_definition_id
  AND tr.test_run_id = :TEST_RUN_ID
  AND tr.result_status = 'Error'
  AND ts.suite_type <> 'contract';
