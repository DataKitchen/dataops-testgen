SELECT schemaname AS schema_name,
    tablename AS table_name,
    columnname AS column_name
FROM svv_external_columns
WHERE schemaname IN ({TEST_SCHEMAS});
