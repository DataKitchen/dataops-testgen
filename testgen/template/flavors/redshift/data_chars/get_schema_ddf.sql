SELECT
       c.table_schema AS schema_name,
       c.table_name,
       c.column_name,
       CASE
           WHEN c.data_type = 'timestamp without time zone' THEN 'timestamp'
           WHEN c.data_type = 'character varying'
               THEN 'varchar(' || CAST(c.character_maximum_length AS VARCHAR) || ')'
           WHEN c.data_type = 'character' THEN 'char(' || CAST(c.character_maximum_length AS VARCHAR) || ')'
           WHEN c.data_type = 'numeric' THEN 'numeric'
                                                || COALESCE( '(' || CAST(c.numeric_precision AS VARCHAR) || ','
                                                                 || CAST(c.numeric_scale AS VARCHAR) || ')', '')
           ELSE c.data_type END AS column_type,
       CASE
           WHEN c.data_type ILIKE 'char%'
               THEN c.data_type || COALESCE('(' || CAST(c.character_maximum_length AS VARCHAR) || ')', '')
           WHEN c.data_type = 'numeric'
               THEN 'numeric' || COALESCE('(' || CAST(c.numeric_precision AS VARCHAR) || ','
                    || CAST(c.numeric_scale AS VARCHAR) || ')', '')
           ELSE c.data_type
       END AS db_data_type,
       c.ordinal_position,
       CASE
           WHEN c.data_type ILIKE 'char%'
               THEN 'A'
           WHEN c.data_type = 'boolean'
               THEN 'B'
           WHEN c.data_type ILIKE 'date'
               OR c.data_type ILIKE 'timestamp%'
               THEN 'D'
           WHEN c.data_type ILIKE 'time with%'
               THEN 'T'
           WHEN LOWER(c.data_type) IN ('bigint', 'integer', 'smallint', 'double precision', 'real', 'numeric')
               THEN 'N'
           ELSE
               'X'
       END AS general_type,
       CASE
         WHEN c.data_type = 'numeric' THEN COALESCE(numeric_scale, 1) > 0
         ELSE numeric_scale > 0
       END AS is_decimal,
       CASE
         WHEN reltuples > 0 AND reltuples < 1 THEN NULL
         ELSE reltuples::BIGINT
       END AS approx_record_ct
FROM information_schema.columns c
    LEFT JOIN pg_namespace n ON c.table_schema = n.nspname
    LEFT JOIN pg_class p ON n.oid = p.relnamespace AND c.table_name = p.relname
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position
