INSERT INTO test_suites
  (project_code, test_suite, connection_id, table_groups_id, test_suite_description,
   component_type, component_key)
VALUES ('{PROJECT_CODE}', '{TEST_SUITE}', {CONNECTION_ID}, '{TABLE_GROUPS_ID}', '{TEST_SUITE} Test Suite',
        'dataset', '{TEST_SUITE}')
RETURNING id::VARCHAR;
