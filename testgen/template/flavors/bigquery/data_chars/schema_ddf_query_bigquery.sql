SELECT '{PROJECT_CODE}' AS project_code,
       CURRENT_TIMESTAMP() AS refresh_timestamp,
       c.table_schema,
       c.table_name,
       c.column_name,
       CASE
           WHEN LOWER(c.data_type) LIKE 'timestamp%' THEN LOWER(c.data_type)
           WHEN LOWER(c.data_type) = 'date' THEN 'date'
           WHEN LOWER(c.data_type) = 'bool' THEN 'boolean'
           ELSE LOWER(c.data_type)
       END AS data_type,
       NULL AS character_maximum_length,
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
       REGEXP_CONTAINS(LOWER(c.data_type), r'(decimal|numeric|bignumeric)') AS is_decimal
FROM `{DATA_SCHEMA}.INFORMATION_SCHEMA.COLUMNS` c
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
