SELECT td.id,
    td.test_type,
    schema_name,
    table_name,
    column_name,
    skip_errors,
    baseline_ct,
    baseline_unique_ct,
    baseline_value,
    baseline_value_ct,
    threshold_value,
    baseline_sum,
    baseline_avg,
    baseline_sd,
    lower_tolerance,
    upper_tolerance,
    subset_condition,
    groupby_names,
    having_condition,
    window_date_column,
    window_days,
    match_schema_name,
    match_table_name,
    match_column_names,
    match_subset_condition,
    match_groupby_names,
    match_having_condition,
    custom_query,
    tt.run_type,
    tt.test_scope,
    tm.template_name,
    c.measure,
    c.test_operator,
    c.test_condition
FROM test_definitions td
    LEFT JOIN test_types tt ON (td.test_type = tt.test_type)
    LEFT JOIN test_templates tm ON (
        td.test_type = tm.test_type
        AND :SQL_FLAVOR = tm.sql_flavor
    )
    LEFT JOIN cat_test_conditions c ON (
        td.test_type = c.test_type
        AND :SQL_FLAVOR = c.sql_flavor
    )
WHERE td.test_suite_id = :TEST_SUITE_ID
    AND td.test_active = 'Y';