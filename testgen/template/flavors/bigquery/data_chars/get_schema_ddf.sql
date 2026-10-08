SELECT
       c.table_schema AS schema_name,
       c.table_name,
       c.column_name,
       CASE
           WHEN LOWER(c.data_type) LIKE 'timestamp%' THEN LOWER(c.data_type)
           WHEN LOWER(c.data_type) = 'date' THEN 'date'
           WHEN LOWER(c.data_type) = 'bool' THEN 'boolean'
           ELSE LOWER(c.data_type)
       END AS column_type,
       c.data_type AS db_data_type,
       CASE
           WHEN LOWER(c.data_type) = 'int64'
               OR REGEXP_CONTAINS(LOWER(c.data_type), r'^(big)?(numeric|decimal)\(\d+(, *0)?\)$') THEN 'integer'
           WHEN LOWER(c.data_type) = 'float64'
               OR REGEXP_CONTAINS(LOWER(c.data_type), r'^(big)?(numeric|decimal)') THEN 'number'
           WHEN REGEXP_CONTAINS(LOWER(c.data_type), r'^(string|bytes)(\(|$)') THEN 'string'
           WHEN LOWER(c.data_type) = 'bool' THEN 'boolean'
           WHEN LOWER(c.data_type) = 'date' THEN 'date'
           WHEN LOWER(c.data_type) IN ('datetime', 'timestamp') THEN 'timestamp'
           WHEN LOWER(c.data_type) = 'time' THEN 'time'
           WHEN LOWER(c.data_type) = 'json'
               OR STARTS_WITH(LOWER(c.data_type), 'struct') THEN 'object'
           WHEN STARTS_WITH(LOWER(c.data_type), 'array') THEN 'array'
       END AS logical_type,
       c.ordinal_position,
       CASE
           WHEN REGEXP_CONTAINS(LOWER(c.data_type), r'^string(\(|$)') THEN 'A'
           WHEN LOWER(c.data_type) = 'bool' THEN 'B'
           WHEN LOWER(c.data_type) IN ('date', 'datetime', 'timestamp') THEN 'D'
           WHEN LOWER(c.data_type) = 'time' THEN 'T'
           WHEN LOWER(c.data_type) IN ('int64', 'float64') THEN 'N'
           WHEN REGEXP_CONTAINS(LOWER(c.data_type), r'^(big)?(numeric|decimal)') THEN 'N'
           ELSE 'X'
       END AS general_type,
       REGEXP_CONTAINS(LOWER(c.data_type), r'^(big)?(numeric|decimal)') AS is_decimal,
       CASE it.table_type
            WHEN 'BASE TABLE' THEN 'TABLE'
            WHEN 'VIEW' THEN 'VIEW'
            WHEN 'MATERIALIZED VIEW' THEN 'MATERIALIZED_VIEW'
            WHEN 'EXTERNAL' THEN 'EXTERNAL'
            ELSE 'OTHER' END AS object_type,
       t.row_count AS approx_record_ct
FROM `{DATA_SCHEMA}.INFORMATION_SCHEMA.COLUMNS` c
    LEFT JOIN `{DATA_SCHEMA}.__TABLES__` t ON c.table_name = t.table_id
    LEFT JOIN `{DATA_SCHEMA}.INFORMATION_SCHEMA.TABLES` it ON c.table_name = it.table_name
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
