SELECT '{PROJECT_CODE}'            as project_code,
       CURRENT_TIMESTAMP AT TIME ZONE 'UTC'                    as refresh_timestamp,
       c.table_schema,
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
       END AS data_type,
       COALESCE(c.character_maximum_length, CASE WHEN c.data_type IN ('text', 'character varying') THEN 65535 END)
          as character_maximum_length,
       c.ordinal_position,
       CASE
           WHEN c.data_type ILIKE '%char%' or c.data_type = 'text'
               THEN 'A'
           WHEN c.data_type ILIKE 'boolean'
               THEN 'B'
           WHEN c.data_type ILIKE 'date'
               OR c.data_type ILIKE 'timestamp%'
               THEN 'D'
           WHEN c.data_type ILIKE 'time without time zone'
               THEN 'T'
           WHEN LOWER(c.data_type) IN ('bigint', 'double precision', 'integer', 'smallint', 'real')
               OR c.data_type ILIKE 'numeric%'
               THEN 'N'
           ELSE
               'X' END          AS general_type,
       CASE
         WHEN c.data_type = 'numeric' THEN COALESCE(numeric_scale, 1) > 0
         ELSE numeric_scale > 0
       END as is_decimal
FROM information_schema.columns c
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position
