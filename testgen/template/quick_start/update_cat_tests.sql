SET SEARCH_PATH TO {SCHEMA_NAME};

UPDATE test_definitions
SET subset_condition = CASE WHEN {ITERATION_NUMBER} <> 3 THEN 'sale_date <= (DATE_TRUNC(''month'', CURRENT_DATE) - (interval ''3 month'' - interval ''{ITERATION_NUMBER} month'') - interval ''1 day'')'
                        ELSE 'sale_date <= (DATE_TRUNC(''month'', CURRENT_DATE) - interval ''1 day'')'
                        END
WHERE test_type='Aggregate_Balance' AND table_name='f_ebike_sales' AND column_name='SUM(total_amount)'
AND test_suite_id = (SELECT id FROM test_suites WHERE test_suite = 'default-suite-1');
