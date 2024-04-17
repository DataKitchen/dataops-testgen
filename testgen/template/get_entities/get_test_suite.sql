SELECT
	id as test_suite_id,
	project_code as project_key,
	test_suite as test_suite_key,
	connection_id,
	test_suite_description,
	test_action as default_test_action,
	test_suite_schema,
	component_key,
	component_type
 FROM test_suites
WHERE project_code = '{PROJECT_CODE}'
AND test_suite = '{TEST_SUITE}';
