SELECT '{PROJECT_CODE}'            as project_code,
       CURRENT_TIMESTAMP                    as refresh_timestamp,
       c.table_schema,
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
       END AS data_type,
       c.character_maximum_length,
       c.ordinal_position,
       CASE
           WHEN c.data_type ILIKE '%char%' OR c.data_type = 'TEXT'
               THEN 'A'
           WHEN c.data_type ILIKE 'boolean'
               THEN 'B'
           WHEN c.data_type ILIKE 'date'
               OR c.data_type ILIKE 'timestamp%'
               THEN 'D'
           WHEN c.data_type = 'time without time zone'
               THEN 'T'
           WHEN lower(c.data_type) IN ('bigint', 'double precision', 'integer', 'smallint', 'real', 'float')
               OR c.data_type ILIKE 'num%'
               THEN 'N'
           ELSE
               'X' END          AS general_type,
       numeric_scale > 0        as is_decimal
FROM information_schema.columns c
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
