SELECT table_schema AS schema_name,
    table_name,
    column_name
FROM information_schema.columns
WHERE table_schema IN ({TEST_SCHEMAS});
