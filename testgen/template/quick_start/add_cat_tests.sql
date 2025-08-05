SET SEARCH_PATH TO {SCHEMA_NAME};

INSERT INTO test_definitions
   (table_groups_id, last_manual_update, schema_name, match_schema_name, test_type,
    test_suite_id, table_name, column_name, skip_errors, threshold_value, subset_condition,
    groupby_names, having_condition, match_table_name, match_column_names, match_subset_condition,
    match_groupby_names, match_having_condition, test_active, severity, watch_level, lock_refresh)
VALUES  ('0ea85e17-acbe-47fe-8394-9970725ad37d', '2024-06-07 02:45:27.102847', :PROJECT_SCHEMA, :PROJECT_SCHEMA,
       'Aggregate_Balance', (SELECT id FROM test_suites WHERE test_suite = 'default-suite-1'),
        'f_ebike_sales', 'SUM(total_amount)', 0, '0', 'sale_date <= (DATE_TRUNC(''month'', CURRENT_DATE) - (interval ''3 month'' - interval ''{ITERATION_NUMBER} month'') - interval ''1 day'')',
        'product_id, sale_date_year, sale_date_month', null, 'tmp_f_ebike_sales_last_month', 'SUM(total_amount)', null, 'product_id, sale_date_year, sale_date_month',
        null, 'Y', null, 'WARN', 'N');
