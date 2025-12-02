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
       c.ordinal_position,
       CASE
           WHEN LOWER(c.data_type) = 'string' THEN 'A'
           WHEN LOWER(c.data_type) = 'bool' THEN 'B'
           WHEN LOWER(c.data_type) IN ('date', 'datetime', 'timestamp') THEN 'D'
           WHEN LOWER(c.data_type) = 'time' THEN 'T'
           WHEN LOWER(c.data_type) IN ('int64', 'float64') THEN 'N'
           WHEN REGEXP_CONTAINS(LOWER(c.data_type), r'(decimal|numeric|bignumeric)') THEN 'N'
           ELSE 'X'
       END AS general_type,
       REGEXP_CONTAINS(LOWER(c.data_type), r'(decimal|numeric|bignumeric)') AS is_decimal,
       t.row_count AS approx_record_ct
FROM `{DATA_SCHEMA}.INFORMATION_SCHEMA.COLUMNS` c
    LEFT JOIN `{DATA_SCHEMA}.__TABLES__` t ON c.table_name = t.table_id
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
