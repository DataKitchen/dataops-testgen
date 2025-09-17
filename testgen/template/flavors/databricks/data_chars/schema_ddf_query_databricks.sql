SELECT '{PROJECT_CODE}' AS project_code,
       CURRENT_TIMESTAMP AS refresh_timestamp,
       c.table_schema,
       c.table_name,
       c.column_name,
       CASE
           WHEN lower(c.full_data_type) = 'timestamp' THEN 'timestamp_ntz'
           WHEN lower(c.full_data_type) = 'string' THEN 'varchar'
           WHEN lower(c.full_data_type) IN ('double', 'float') THEN 'numeric'
           WHEN lower(c.full_data_type) LIKE 'decimal%' THEN 'numeric(' || c.numeric_precision || ',' || c.numeric_scale || ')'
           ELSE lower(c.full_data_type)
       END AS data_type,
       c.character_maximum_length,
       c.ordinal_position,
       CASE
           WHEN c.data_type IN ('STRING', 'CHAR') THEN 'A'
           WHEN c.data_type = 'BOOLEAN' THEN 'B'
           WHEN c.data_type IN ('DATE', 'TIMESTAMP', 'TIMESTAMP_NTZ') THEN 'D'
           WHEN c.data_type IN ('BYTE', 'SHORT', 'INT', 'LONG', 'DECIMAL', 'FLOAT', 'DOUBLE') THEN 'N'
           ELSE 'X'
       END AS general_type,
       CASE
           WHEN c.numeric_scale > 0 THEN 1
           ELSE 0
       END AS is_decimal
FROM information_schema.columns c
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
