SELECT
       c.table_schema AS schema_name,
       c.table_name,
       c.column_name,
       CASE
           WHEN c.data_type ILIKE 'timestamp%' THEN lower(c.data_type)
           WHEN c.data_type ILIKE 'date' THEN lower(c.data_type)
           WHEN c.data_type ILIKE 'boolean' THEN 'boolean'
           WHEN c.data_type = 'TEXT'
               THEN 'varchar(' || CAST(c.character_maximum_length AS VARCHAR) || ')'
           WHEN c.data_type ILIKE 'char%' THEN 'char(' || CAST(c.character_maximum_length AS VARCHAR) || ')'
           WHEN c.data_type = 'NUMBER' AND c.numeric_precision = 38 AND c.numeric_scale = 0 THEN 'bigint'
           WHEN c.data_type ILIKE 'num%' THEN 'numeric(' || CAST(c.numeric_precision AS VARCHAR) || ',' ||
                                             CAST(c.numeric_scale AS VARCHAR) || ')'
           ELSE c.data_type
       END AS column_type,
       CASE
           WHEN c.data_type = 'TEXT'
               THEN 'VARCHAR' || COALESCE('(' || CAST(c.character_maximum_length AS VARCHAR) || ')', '')
           WHEN c.data_type = 'NUMBER'
               THEN c.data_type || COALESCE('(' || CAST(c.numeric_precision AS VARCHAR) || ','
                   || CAST(c.numeric_scale AS VARCHAR) || ')', '')
           WHEN c.data_type ILIKE 'TIME%'
               THEN c.data_type || COALESCE('(' || CAST(c.datetime_precision AS VARCHAR) || ')', '')
           ELSE c.data_type
       END AS db_data_type,
       c.ordinal_position,
       CASE
           WHEN c.data_type = 'TEXT'
               THEN 'A'
           WHEN c.data_type = 'BOOLEAN'
               THEN 'B'
           WHEN c.data_type = 'DATE'
               OR c.data_type ILIKE 'TIMESTAMP%'
               THEN 'D'
           WHEN c.data_type = 'TIME'
               THEN 'T'
           WHEN c.data_type = 'NUMBER'
               OR c.data_type = 'FLOAT'
               THEN 'N'
           ELSE
               'X'
           END AS general_type,
       numeric_scale > 0 AS is_decimal,
       t.row_count AS approx_record_ct
FROM information_schema.columns c
    LEFT JOIN information_schema.tables t ON c.table_schema = t.table_schema AND c.table_name = t.table_name
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
