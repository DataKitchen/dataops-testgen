WITH approx_cts AS (
    SELECT SCHEMA_NAME(o.schema_id) AS schema_name,
        o.name AS table_name,
        SUM(p.rows) AS approx_record_ct
    FROM sys.objects o
        LEFT JOIN sys.partitions p ON p.object_id = o.object_id
    WHERE p.index_id IN (0, 1) -- 0 = heap, 1 = clustered index
        OR p.index_id IS NULL
    GROUP BY o.schema_id, o.name
)
SELECT
       c.table_schema AS schema_name,
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
           ELSE c.data_type END AS column_type,
       CASE
           WHEN c.data_type LIKE '%char' OR c.data_type LIKE '%binary'
               THEN c.data_type + COALESCE('(' + CAST(c.character_maximum_length AS VARCHAR) + ')', '')
           WHEN c.data_type IN ('datetime2', 'datetimeoffset', 'time')
               THEN c.data_type + COALESCE('(' + CAST(c.datetime_precision AS VARCHAR) + ')', '')
           WHEN c.data_type IN ('numeric', 'decimal')
               THEN c.data_type + COALESCE('(' + CAST(c.numeric_precision AS VARCHAR) + ','
                   + CAST(c.numeric_scale AS VARCHAR) + ')', '')
       ELSE c.data_type END AS db_data_type,
       c.ordinal_position,
       CASE
           WHEN LOWER(c.data_type) LIKE '%char%'
               THEN 'A'
           WHEN c.data_type = 'bit'
               THEN 'B'
           WHEN c.data_type = 'date'
               OR c.data_type LIKE '%datetime%'
               THEN 'D'
           WHEN c.data_type = 'time'
               THEN 'T'
           WHEN c.data_type IN ('real', 'float', 'decimal', 'numeric')
               OR c.data_type LIKE '%int'
               OR c.data_type LIKE '%money'
               THEN 'N'
           ELSE
               'X'
       END AS general_type,
       CASE WHEN c.numeric_scale > 0 THEN 1 ELSE 0 END AS is_decimal,
       a.approx_record_ct AS approx_record_ct
FROM information_schema.columns c
    LEFT JOIN approx_cts a ON c.table_schema = a.schema_name AND c.table_name = a.table_name
WHERE c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
