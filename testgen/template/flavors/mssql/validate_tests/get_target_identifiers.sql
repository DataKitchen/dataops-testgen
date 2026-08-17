-- Uppercase INFORMATION_SCHEMA object names (Fabric is case-sensitive on
-- catalog names); keep column projections lowercase, driver returns keys as-typed.
SELECT table_schema AS schema_name,
    table_name,
    column_name
FROM INFORMATION_SCHEMA.COLUMNS
WHERE table_schema IN ({TEST_SCHEMAS});
