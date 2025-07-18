-- ==============================================================================
-- |   Table Characteristics
-- ==============================================================================

-- Update existing records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      functional_table_type,
      run_date,
      MAX(record_ct) AS record_ct,
      COUNT(*) AS column_ct
   FROM {SOURCE_TABLE}
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id,
      schema_name,
      table_name,
      functional_table_type,
      run_date
)
UPDATE data_table_chars
SET functional_table_type = COALESCE(n.functional_table_type, d.functional_table_type),
   record_ct = n.record_ct,
   column_ct = n.column_ct,
   last_refresh_date = n.run_date,
   drop_date = NULL
FROM new_chars n
   INNER JOIN data_table_chars d ON (
      n.table_groups_id = d.table_groups_id
      AND n.schema_name = d.schema_name
      AND n.table_name = d.table_name
   )
WHERE data_table_chars.table_id = d.table_id;

-- Add new records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      functional_table_type,
      run_date,
      MAX(record_ct) AS record_ct,
      COUNT(*) AS column_ct
   FROM {SOURCE_TABLE}
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id,
      schema_name,
      table_name,
      functional_table_type,
      run_date
)
INSERT INTO data_table_chars (
      table_groups_id,
      schema_name,
      table_name,
      functional_table_type,
      add_date,
      last_refresh_date,
      record_ct,
      column_ct
   )
SELECT n.table_groups_id,
   n.schema_name,
   n.table_name,
   n.functional_table_type,
   n.run_date,
   n.run_date,
   n.record_ct,
   n.column_ct
FROM new_chars n
   LEFT JOIN data_table_chars d ON (
      n.table_groups_id = d.table_groups_id
      AND n.schema_name = d.schema_name
      AND n.table_name = d.table_name
   )
WHERE d.table_id IS NULL;

-- Mark dropped records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name
   FROM {SOURCE_TABLE}
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id,
      schema_name,
      table_name
),
last_run AS (
   SELECT table_groups_id,
      MAX(run_date) as last_run_date
   FROM {SOURCE_TABLE}
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id
)
UPDATE data_table_chars
SET drop_date = l.last_run_date
FROM last_run l
   INNER JOIN data_table_chars d ON (l.table_groups_id = d.table_groups_id)
   LEFT JOIN new_chars n ON (
      d.table_groups_id = n.table_groups_id
      AND d.schema_name = n.schema_name
      AND d.table_name = n.table_name
   )
WHERE data_table_chars.table_id = d.table_id
   AND d.drop_date IS NULL
   AND n.table_name IS NULL;

-- ==============================================================================
-- |   Column Characteristics
-- ==============================================================================

-- Update existing records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      column_name,
      position,
      general_type,
      column_type,
      functional_data_type,
      run_date
   FROM {SOURCE_TABLE}
   WHERE table_groups_id = :TABLE_GROUPS_ID
)
UPDATE data_column_chars
SET ordinal_position = n.position,
   general_type = n.general_type,
   column_type = n.column_type,
   functional_data_type = COALESCE(n.functional_data_type, d.functional_data_type),
   last_mod_date = CASE WHEN n.column_type <> d.column_type THEN n.run_date ELSE d.last_mod_date END,
   drop_date = NULL
FROM new_chars n
   INNER JOIN data_column_chars d ON (
      n.table_groups_id = d.table_groups_id
      AND n.schema_name = d.schema_name
      AND n.table_name = d.table_name
      AND n.column_name = d.column_name
   )
WHERE data_column_chars.table_id = d.table_id
   AND data_column_chars.column_name = d.column_name;

-- Add new records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      column_name,
      position,
      general_type,
      column_type,
      functional_data_type,
      run_date
   FROM {SOURCE_TABLE}
   WHERE table_groups_id = :TABLE_GROUPS_ID
)
INSERT INTO data_column_chars (
      table_groups_id,
      schema_name,
      table_name,
      table_id,
      column_name,
      ordinal_position,
      general_type,
      column_type,
      functional_data_type,
      add_date,
      last_mod_date
   )
SELECT n.table_groups_id,
   n.schema_name,
   n.table_name,
   dtc.table_id,
   n.column_name,
   n.position,
   n.general_type,
   n.column_type,
   n.functional_data_type,
   n.run_date,
   n.run_date
FROM new_chars n
   INNER JOIN data_table_chars dtc ON (
      n.table_groups_id = dtc.table_groups_id
      AND n.schema_name = dtc.schema_name
      AND n.table_name = dtc.table_name
   )
   LEFT JOIN data_column_chars d ON (
      n.table_groups_id = d.table_groups_id
      AND n.schema_name = d.schema_name
      AND n.table_name = d.table_name
      AND n.column_name = d.column_name
   )
WHERE d.table_id IS NULL;

-- Mark dropped records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      column_name
   FROM {SOURCE_TABLE}
   WHERE table_groups_id = :TABLE_GROUPS_ID
),
last_run AS (
   SELECT table_groups_id,
      MAX(run_date) as last_run_date
   FROM {SOURCE_TABLE}
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id
)
UPDATE data_column_chars
SET drop_date = l.last_run_date
FROM last_run l
   INNER JOIN data_column_chars d ON (l.table_groups_id = d.table_groups_id)
   LEFT JOIN new_chars n ON (
      d.table_groups_id = n.table_groups_id
      AND d.schema_name = n.schema_name
      AND d.table_name = n.table_name
      AND d.column_name = n.column_name
   )
WHERE data_column_chars.table_id = d.table_id
   AND data_column_chars.column_name = d.column_name
   AND d.drop_date IS NULL
   AND n.column_name IS NULL;
