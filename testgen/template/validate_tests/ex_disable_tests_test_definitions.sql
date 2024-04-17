update test_definitions
set test_active = 'N'
 where project_code = '{PROJECT_CODE}'
   and test_suite = '{TEST_SUITE}'
   and test_active = 'D';
