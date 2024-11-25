SELECT '{PROJECT_CODE}' AS project_code,
       CURRENT_TIMESTAMP AS refresh_timestamp,
       c.table_schema,
       c.table_name,
       c.column_name,
       CASE
           WHEN c.data_type = 'datetime' THEN 'datetime'
           WHEN c.data_type = 'datetime2' THEN 'datetime'
           WHEN c.data_type = 'varchar'
               THEN CONCAT('varchar(', CAST(c.character_maximum_length AS STRING), ')')
           WHEN c.data_type = 'char'
               THEN CONCAT('char(', CAST(c.character_maximum_length AS STRING), ')')
           WHEN c.data_type = 'numeric'
               THEN CONCAT('numeric(', CAST(c.numeric_precision AS STRING), ',', CAST(c.numeric_scale AS STRING), ')')
           ELSE c.data_type
       END AS data_type,
       c.character_maximum_length,
       c.ordinal_position,
       CASE
           WHEN LOWER(c.data_type) LIKE '%char%' THEN 'A'
           WHEN c.data_type = 'bit' THEN 'B'
           WHEN c.data_type = 'date' OR c.data_type LIKE 'datetime%' THEN 'D'
           WHEN c.data_type LIKE 'time%' THEN 'T'
           WHEN c.data_type IN ('bigint', 'double precision', 'integer', 'smallint', 'real')
                OR c.data_type LIKE 'numeric%' THEN 'N'
           ELSE 'X'
       END AS general_type,
       CASE
           WHEN c.numeric_scale > 0 THEN 1
           ELSE 0
       END AS is_decimal
FROM information_schema.columns c
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
