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
           -- datetime_precision reports the default 6 for an undeclared precision; atttypmod is -1 there
           WHEN c.data_type ILIKE 'time%' AND a.atttypmod <> -1
               THEN REGEXP_REPLACE(c.data_type, '^(time|timestamp)', '\1(' || CAST(c.datetime_precision AS VARCHAR) || ')')
           ELSE c.data_type
       END AS db_data_type,
       CASE
           WHEN LOWER(c.data_type) IN ('bigint', 'integer', 'smallint')
               OR (c.data_type = 'numeric' AND c.numeric_scale = 0)
               THEN 'integer'
           WHEN LOWER(c.data_type) IN ('double precision', 'real', 'numeric', 'money')
               THEN 'number'
           WHEN c.data_type ILIKE '%char%' OR c.data_type IN ('text', 'uuid', 'bytea', 'xml')
               THEN 'string'
           WHEN c.data_type ILIKE 'boolean'
               THEN 'boolean'
           WHEN c.data_type ILIKE 'date'
               THEN 'date'
           WHEN c.data_type ILIKE 'timestamp%'
               THEN 'timestamp'
           WHEN c.data_type ILIKE 'time with%'
               THEN 'time'
           WHEN c.data_type IN ('json', 'jsonb')
               THEN 'object'
           WHEN c.data_type = 'ARRAY'
               THEN 'array'
       END AS logical_type,
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
       CASE p.relkind
            WHEN 'r' THEN 'TABLE' WHEN 'p' THEN 'TABLE'
            WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED_VIEW' WHEN 'f' THEN 'EXTERNAL'
            ELSE 'OTHER' END AS object_type,
       NULLIF(p.reltuples::BIGINT, -1) AS approx_record_ct
FROM information_schema.columns c
    LEFT JOIN pg_namespace n ON c.table_schema = n.nspname
    LEFT JOIN pg_class p ON n.oid = p.relnamespace AND c.table_name = p.relname
    LEFT JOIN pg_attribute a ON p.oid = a.attrelid AND c.column_name = a.attname
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position
