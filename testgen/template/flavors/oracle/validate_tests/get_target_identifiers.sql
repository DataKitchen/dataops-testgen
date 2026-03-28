SELECT owner AS schema_name,
    table_name,
    column_name
FROM all_tab_columns
WHERE owner IN ({TEST_SCHEMAS})
