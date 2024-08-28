UPDATE test_definitions
   SET test_active = 'N'
 WHERE test_suite_id = '{TEST_SUITE_ID}'
   AND test_active = 'D';
