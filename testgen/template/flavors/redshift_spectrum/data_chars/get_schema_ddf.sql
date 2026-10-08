SELECT
    c.schemaname AS schema_name,
    c.tablename AS table_name,
    c.columnname AS column_name,
    c.external_type AS column_type,
    c.external_type AS db_data_type,
    CASE
        WHEN c.external_type IN ('tinyint', 'smallint', 'int', 'integer', 'bigint', 'long')
            OR REGEXP_SUBSTR(c.external_type, 'decimal\\([0-9]+,([0-9]+)\\)', 1, 1, 'e') = '0'
            THEN 'integer'
        WHEN c.external_type IN ('double', 'float', 'real')
            OR c.external_type ILIKE 'decimal%'
            THEN 'number'
        WHEN c.external_type IN ('string', 'binary')
            OR c.external_type ILIKE 'varchar%'
            OR c.external_type ILIKE 'char%'
            THEN 'string'
        WHEN c.external_type = 'boolean'
            THEN 'boolean'
        WHEN c.external_type = 'date'
            THEN 'date'
        WHEN c.external_type = 'timestamp'
            THEN 'timestamp'
        WHEN c.external_type ILIKE 'array<%'
            THEN 'array'
        WHEN c.external_type ILIKE 'map<%'
            THEN 'map'
        WHEN c.external_type ILIKE 'struct<%'
            THEN 'object'
    END AS logical_type,
    c.columnnum AS ordinal_position,
    CASE
        WHEN c.external_type = 'string'
            OR c.external_type ILIKE 'varchar%'
            OR c.external_type ILIKE 'char%'
            THEN 'A'
        WHEN c.external_type = 'boolean'
            THEN 'B'
        WHEN c.external_type IN ('date', 'timestamp')
            THEN 'D'
        WHEN c.external_type IN ('tinyint', 'smallint', 'int', 'integer', 'bigint', 'long', 'double', 'float', 'real')
            OR c.external_type ILIKE 'decimal%'
            THEN 'N'
        ELSE 'X'
    END AS general_type,
    CASE
        WHEN REGEXP_SUBSTR(c.external_type, 'decimal\\([0-9]+,([0-9]+)\\)', 1, 1, 'e') > 0
            THEN 1
        ELSE 0
    END AS is_decimal,
    'EXTERNAL' AS object_type,
    NULL AS approx_record_ct -- Table statistics unavailable
FROM svv_external_columns c
WHERE c.schemaname = '{DATA_SCHEMA}'
    {TABLE_CRITERIA}
ORDER BY c.schemaname,
    c.tablename,
    c.columnnum