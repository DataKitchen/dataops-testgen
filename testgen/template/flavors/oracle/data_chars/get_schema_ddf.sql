SELECT
    c.owner AS schema_name,
    c.table_name,
    c.column_name,
    CASE
        WHEN c.data_type IN ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR') THEN 'char(' || c.data_length || ')'
        WHEN c.data_type = 'NUMBER' AND c.data_precision IS NOT NULL AND c.data_scale = 0 THEN 'bigint'
        WHEN c.data_type = 'NUMBER' AND c.data_precision IS NOT NULL THEN 'numeric(' || c.data_precision || ',' || c.data_scale || ')'
        WHEN c.data_type = 'NUMBER' THEN 'int'
        WHEN c.data_type IN ('FLOAT', 'BINARY_FLOAT', 'BINARY_DOUBLE') THEN 'numeric'
        WHEN c.data_type LIKE 'TIMESTAMP%' THEN 'timestamp'
        ELSE LOWER(c.data_type)
    END AS column_type,
    CASE
        -- Lengths as the column declares them: national types in characters, the others in characters
        -- only under character length semantics. data_length is always bytes.
        WHEN c.data_type IN ('NVARCHAR2', 'NCHAR') THEN c.data_type || '(' || c.char_length || ')'
        WHEN c.data_type IN ('VARCHAR2', 'CHAR') AND c.char_used = 'C' THEN c.data_type || '(' || c.char_length || ' CHAR)'
        WHEN c.data_type IN ('VARCHAR2', 'CHAR') THEN c.data_type || '(' || c.data_length || ')'
        WHEN c.data_type = 'NUMBER' AND c.data_precision IS NOT NULL THEN 'NUMBER(' || c.data_precision || ',' || c.data_scale || ')'
        WHEN c.data_type = 'FLOAT' THEN 'FLOAT(' || c.data_precision || ')'
        ELSE c.data_type
    END AS db_data_type,
    CASE
        WHEN c.data_type = 'NUMBER' AND c.data_scale = 0 THEN 'integer'
        WHEN c.data_type IN ('NUMBER', 'FLOAT', 'BINARY_FLOAT', 'BINARY_DOUBLE') THEN 'number'
        WHEN c.data_type IN ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR', 'CLOB', 'NCLOB', 'LONG',
                             'RAW', 'LONG RAW', 'BLOB', 'XMLTYPE', 'ROWID', 'UROWID') THEN 'string'
        WHEN c.data_type = 'BOOLEAN' THEN 'boolean'
        WHEN c.data_type = 'DATE' THEN 'date'
        WHEN c.data_type LIKE 'TIMESTAMP%' THEN 'timestamp'
        WHEN c.data_type = 'JSON' THEN 'object'
    END AS logical_type,
    c.column_id AS ordinal_position,
    CASE
        WHEN c.data_type IN ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR')
            THEN 'A'
        WHEN c.data_type = 'BOOLEAN'
            THEN 'B'
        WHEN c.data_type = 'DATE' OR c.data_type LIKE 'TIMESTAMP%'
            THEN 'D'
        WHEN c.data_type IN ('NUMBER', 'FLOAT', 'BINARY_FLOAT', 'BINARY_DOUBLE')
            THEN 'N'
        ELSE 'X'
    END AS general_type,
    CASE
        WHEN c.data_type = 'NUMBER' AND c.data_scale > 0 THEN 1
        ELSE 0
    END AS is_decimal,
    CASE WHEN t.table_name IS NOT NULL THEN 'TABLE'
         WHEN EXISTS (SELECT 1 FROM all_views v WHERE v.owner = c.owner AND v.view_name = c.table_name) THEN 'VIEW'
         ELSE 'OTHER' END AS object_type,
    t.num_rows AS approx_record_ct
FROM all_tab_columns c
LEFT JOIN all_tables t ON c.owner = t.owner AND c.table_name = t.table_name
WHERE c.owner = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.owner, c.table_name, c.column_id
