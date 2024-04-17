SELECT '{PROJECT_CODE}'            as project_code,
       CURRENT_TIMESTAMP           as refresh_timestamp,
       c.table_schema,
       c.table_name,
       c.column_name,
       CASE
           WHEN c.data_type = 'datetime' THEN 'datetime'
           WHEN c.data_type = 'datetime2' THEN 'datetime'
           WHEN c.data_type = 'varchar'
               THEN 'varchar(' + CAST(c.character_maximum_length AS VARCHAR) + ')'
           WHEN c.data_type = 'char' THEN 'char(' + CAST(c.character_maximum_length AS VARCHAR) + ')'
           WHEN c.data_type = 'numeric' THEN 'numeric(' + CAST(c.numeric_precision AS VARCHAR) + ',' +
                                             CAST(c.numeric_scale AS VARCHAR) + ')'
           ELSE c.data_type END AS data_type,
       c.character_maximum_length,
       c.ordinal_position,
       CASE
           WHEN LOWER(c.data_type) LIKE '%char%'
               THEN 'A'
           WHEN c.data_type = 'bit'
               THEN 'B'
           WHEN c.data_type = 'date'
               OR c.data_type LIKE 'datetime%'
               THEN 'D'
           WHEN c.data_type like 'time%'
               THEN 'T'
           WHEN c.data_type IN ('bigint', 'double precision', 'integer', 'smallint', 'real')
               OR c.data_type LIKE 'numeric%'
               THEN 'N'
           ELSE
               'X' END          AS general_type,
       case when c.numeric_scale > 0 then 1 else 0 END       as is_decimal
FROM information_schema.columns c
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
