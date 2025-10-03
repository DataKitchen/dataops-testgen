SELECT
       c.table_schema AS schema_name,
       c.table_name,
       c.column_name,
       CASE
           WHEN c.data_type = 'timestamp without time zone' THEN 'timestamp'
           WHEN c.data_type = 'text'
             OR (c.data_type = 'character varying' and c.character_maximum_length is NULL)  THEN 'varchar(65535)'
           WHEN c.data_type = 'character varying'
               THEN 'varchar(' || CAST(c.character_maximum_length AS VARCHAR) || ')'
           WHEN c.data_type = 'character' THEN 'char(' || CAST(c.character_maximum_length AS VARCHAR) || ')'
           WHEN c.data_type = 'numeric' THEN 'numeric'
                                                || COALESCE( '(' || CAST(c.numeric_precision AS VARCHAR) || ','
                                                                 || CAST(c.numeric_scale AS VARCHAR) || ')', '')
           ELSE c.data_type
       END AS column_type,
       CASE
           WHEN c.data_type ILIKE 'char%' OR c.data_type ILIKE 'bit%'
               THEN c.data_type || COALESCE('(' || CAST(c.character_maximum_length AS VARCHAR) || ')', '')
           WHEN c.data_type = 'numeric'
               THEN 'numeric' || COALESCE('(' || CAST(c.numeric_precision AS VARCHAR) || ','
                    || CAST(c.numeric_scale AS VARCHAR) || ')', '')
           WHEN c.data_type ILIKE 'time%'
               THEN c.data_type || COALESCE('(' ||  CAST(c.datetime_precision AS VARCHAR) || ')', '')
           ELSE c.data_type
       END AS db_data_type,
       c.ordinal_position,
       CASE
           WHEN c.data_type ILIKE '%char%' or c.data_type = 'text'
               THEN 'A'
           WHEN c.data_type ILIKE 'boolean'
               THEN 'B'
           WHEN c.data_type ILIKE 'date'
               OR c.data_type ILIKE 'timestamp%'
               THEN 'D'
           WHEN c.data_type ILIKE 'time with%'
               THEN 'T'
           WHEN LOWER(c.data_type) IN ('bigint', 'integer', 'smallint', 'double precision', 'real', 'numeric', 'money')
               THEN 'N'
           ELSE
               'X'
       END AS general_type,
       CASE
         WHEN c.data_type = 'numeric' THEN COALESCE(numeric_scale, 1) > 0
         ELSE numeric_scale > 0
       END as is_decimal,
       NULLIF(p.reltuples::BIGINT, -1) AS approx_record_ct
FROM information_schema.columns c
    LEFT JOIN pg_namespace n ON c.table_schema = n.nspname
    LEFT JOIN pg_class p ON n.oid = p.relnamespace AND c.table_name = p.relname
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position
