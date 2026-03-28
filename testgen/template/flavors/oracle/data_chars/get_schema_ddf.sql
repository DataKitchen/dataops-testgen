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
        WHEN c.data_type IN ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR') THEN c.data_type || '(' || c.data_length || ')'
        WHEN c.data_type = 'NUMBER' AND c.data_precision IS NOT NULL THEN 'NUMBER(' || c.data_precision || ',' || c.data_scale || ')'
        WHEN c.data_type = 'FLOAT' THEN 'FLOAT(' || c.data_precision || ')'
        ELSE c.data_type
    END AS db_data_type,
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
    t.num_rows AS approx_record_ct
FROM all_tab_columns c
LEFT JOIN all_tables t ON c.owner = t.owner AND c.table_name = t.table_name
WHERE c.owner = '{DATA_SCHEMA}' {TABLE_CRITERIA}
ORDER BY c.owner, c.table_name, c.column_id
