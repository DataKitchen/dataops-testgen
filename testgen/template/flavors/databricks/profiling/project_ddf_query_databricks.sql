SELECT '{PROJECT_CODE}' AS project_code,
       CURRENT_TIMESTAMP AS refresh_timestamp,
       c.table_schema,
       c.table_name,
       c.column_name,
       CASE
           WHEN lower(c.data_type) IN ('date', 'timestamp', 'timestamp_ntz') THEN 'datetime'
           WHEN lower(c.data_type) = 'string' THEN 'varchar'
           WHEN lower(c.data_type) = 'decimal' THEN concat('numeric(', c.numeric_precision, ',', c.numeric_scale, ')')
           WHEN lower(c.data_type) IN ('bigint', 'double', 'float', 'int', 'smallint', 'tinyint') THEN 'numeric'
           ELSE lower(c.data_type)
       END AS data_type,
       c.character_maximum_length,
       c.ordinal_position,
       CASE
           WHEN lower(c.data_type) RLIKE '(string|char|varchar|text)' THEN 'A'
           WHEN lower(c.data_type) RLIKE 'boolean' THEN 'B'
           WHEN lower(c.data_type) IN ('date', 'timestamp') THEN 'D'
           WHEN lower(c.data_type) IN ('time', 'interval') THEN 'T'
           WHEN lower(c.data_type) IN ('byte', 'short', 'int', 'integer', 'long', 'bigint', 'float', 'double') THEN 'N'
           WHEN lower(c.data_type) LIKE 'decimal%' THEN 'N'
           ELSE 'X'
       END AS general_type,
       CASE
           WHEN c.numeric_scale > 0 THEN 1
           ELSE 0
       END AS is_decimal
FROM information_schema.columns c
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
