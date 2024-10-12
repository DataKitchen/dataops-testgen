INSERT INTO test_results
          ( test_suite_id,
            test_type,
            test_definition_id,
            schema_name,
            table_name,
            column_names,
            test_time,
            test_run_id,
            input_parameters,
            result_code,
            result_message,
            result_measure )
     SELECT '{TEST_SUITE_ID}'::UUID,
            test_type,
            id,
            schema_name,
            table_name,
            column_name,
            '{RUN_DATE}'    as test_time,
            '{TEST_RUN_ID}' as test_run_id,
            NULL as input_parameters,
            0 as result_code,
            test_definition_status AS result_message,
            NULL as result_measure
       FROM test_definitions
      WHERE test_active = 'D'
        AND test_suite_id = '{TEST_SUITE_ID}';
