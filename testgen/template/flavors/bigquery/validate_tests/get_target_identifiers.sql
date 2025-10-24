SELECT table_schema AS schema_name,
    table_name,
    column_name
FROM `{DATA_SCHEMA}.INFORMATION_SCHEMA.COLUMNS`
WHERE table_schema IN ({TEST_SCHEMAS});
