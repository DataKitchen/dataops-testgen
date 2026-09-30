-- DuckDB reports data_type as a self-contained string ("VARCHAR", "DECIMAL(12,4)",
-- "TIMESTAMP WITH TIME ZONE", "INTEGER[]", "MAP(VARCHAR, INTEGER)"), so db_data_type is that
-- string and column_type is its normalized form.
--
-- An ENUM spells its values out. Both columns report it as the bare type name instead, and drop any
-- quote surviving elsewhere, as in a nested type holding an ENUM.
--
-- Type names are matched exactly rather than by substring: a nested type spells out the types it
-- contains, so MAP(VARCHAR, INTEGER) and STRUCT(y VARCHAR) both contain "VARCHAR" without being
-- text, and DECIMAL(12,4)[] contains "DECIMAL(" without being a number. A list is written
-- "TYPE[]" and a fixed-size array "TYPE[3]", so both are caught by the closing bracket.
-- numeric_precision carries the fixed-width numeric types; the unsigned integers and BIGNUM
-- report it as NULL, so those are named outright.
--
-- character_maximum_length is always NULL, including for VARCHAR(50) and CHAR(3), so every string
-- column is unbounded. Row estimates come from duckdb_tables(); duckdb_views() carries none,
-- leaving approx_record_ct NULL for views.
SELECT
       c.table_schema AS schema_name,
       c.table_name,
       c.column_name,
       CASE
           WHEN c.numeric_precision IS NOT NULL AND c.data_type LIKE 'DECIMAL(%'
               THEN 'numeric(' || CAST(c.numeric_precision AS VARCHAR) || ','
                                || CAST(c.numeric_scale AS VARCHAR) || ')'
           WHEN c.data_type = 'VARCHAR' OR c.data_type LIKE 'ENUM(%'
               THEN 'varchar(65535)'
           ELSE REPLACE(LOWER(c.data_type), '''', '')
       END AS column_type,
       CASE
           WHEN c.data_type LIKE 'ENUM(%' THEN 'ENUM'
           ELSE REPLACE(c.data_type, '''', '')
       END AS db_data_type,
       c.ordinal_position,
       CASE
           WHEN c.data_type LIKE '%]'
                OR c.data_type LIKE 'STRUCT(%'
                OR c.data_type LIKE 'MAP(%'
                OR c.data_type LIKE 'UNION(%'
               THEN 'X'
           WHEN c.numeric_precision IS NOT NULL
                OR c.data_type IN ('UTINYINT', 'USMALLINT', 'UINTEGER', 'UBIGINT', 'UHUGEINT', 'BIGNUM')
               THEN 'N'
           WHEN c.data_type = 'VARCHAR' OR c.data_type LIKE 'ENUM(%'
               THEN 'A'
           WHEN c.data_type = 'BOOLEAN'
               THEN 'B'
           WHEN c.data_type IN ('DATE', 'TIMESTAMP', 'TIMESTAMP WITH TIME ZONE',
                                'TIMESTAMP_S', 'TIMESTAMP_MS', 'TIMESTAMP_NS')
               THEN 'D'
           WHEN c.data_type IN ('TIME', 'TIME WITH TIME ZONE', 'TIME_NS')
               THEN 'T'
           ELSE
               'X'
       END AS general_type,
       COALESCE(c.numeric_scale, 0) > 0 AS is_decimal,
       CASE t.table_type
            WHEN 'BASE TABLE' THEN 'TABLE'
            WHEN 'VIEW' THEN 'VIEW'
            ELSE 'OTHER' END AS object_type,
       d.estimated_size AS approx_record_ct
FROM information_schema.columns c
    LEFT JOIN information_schema.tables t
        ON c.table_catalog = t.table_catalog
       AND c.table_schema = t.table_schema AND c.table_name = t.table_name
    LEFT JOIN duckdb_tables() d
        ON d.database_name = current_database()
       AND c.table_schema = d.schema_name AND c.table_name = d.table_name
-- information_schema spans every attached database, and a temp table shares the default schema
-- name, so without the catalog predicate an unrelated table of the same name is reported as the
-- customer's.
WHERE c.table_catalog = current_database()
  AND c.table_schema = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.table_schema, c.table_name, c.ordinal_position
