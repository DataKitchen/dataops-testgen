SELECT
       c.table_schema AS schema_name,
       c.table_name,
       c.column_name,
       CASE
           WHEN lower(c.full_data_type) = 'timestamp' THEN 'timestamp_ntz'
           WHEN lower(c.full_data_type) = 'string' THEN 'varchar'
           WHEN lower(c.full_data_type) IN ('double', 'float') THEN 'numeric'
           WHEN lower(c.full_data_type) LIKE 'decimal%' THEN 'numeric(' || c.numeric_precision || ',' || c.numeric_scale || ')'
           ELSE lower(c.full_data_type)
       END AS column_type,
       c.full_data_type AS db_data_type,
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
       END AS is_decimal,
       NULL AS approx_record_ct -- table statistics unavailable
FROM information_schema.columns c
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
