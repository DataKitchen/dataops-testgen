UPDATE test_definitions td
SET test_active = 'N',
  test_definition_status = LEFT('Deactivated ' || :RUN_DATE || '. ' || REGEXP_REPLACE(tr.result_message, '^Deactivated\.\s*', ''), 200)
FROM test_results tr
  INNER JOIN test_suites ts ON ts.id = tr.test_suite_id
WHERE td.id = tr.test_definition_id
  AND tr.test_run_id = :TEST_RUN_ID
  AND tr.result_status = 'Error'
  AND tr.result_message LIKE 'Deactivated.%'
  AND ts.suite_type <> 'contract';
