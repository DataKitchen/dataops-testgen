-- ==============================================================================
-- |   Table Characteristics
-- ==============================================================================

-- Update existing records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      run_date,
      MAX(approx_record_ct) AS approx_record_ct,
      MAX(record_ct) AS record_ct,
      COUNT(*) AS column_ct
   FROM stg_data_chars_updates
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id,
      schema_name,
      table_name,
      run_date
)
UPDATE data_table_chars
SET approx_record_ct = n.approx_record_ct,
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
      run_date,
      MAX(approx_record_ct) AS approx_record_ct,
      MAX(record_ct) AS record_ct,
      COUNT(*) AS column_ct
   FROM stg_data_chars_updates
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id,
      schema_name,
      table_name,
      run_date
)
INSERT INTO data_table_chars (
      table_groups_id,
      schema_name,
      table_name,
      add_date,
      last_refresh_date,
      approx_record_ct,
      record_ct,
      column_ct
   )
SELECT n.table_groups_id,
   n.schema_name,
   n.table_name,
   n.run_date,
   n.run_date,
   n.approx_record_ct,
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
   FROM stg_data_chars_updates
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id,
      schema_name,
      table_name
),
last_run AS (
   SELECT table_groups_id,
      MAX(run_date) as last_run_date
   FROM stg_data_chars_updates
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
      column_type,
      db_data_type,
      run_date
   FROM stg_data_chars_updates
   WHERE table_groups_id = :TABLE_GROUPS_ID
),
update_chars AS (
   UPDATE data_column_chars
   SET ordinal_position = n.position,
      column_type = n.column_type,
      db_data_type = n.db_data_type,
      last_mod_date = CASE WHEN n.db_data_type <> d.db_data_type THEN n.run_date ELSE d.last_mod_date END,
      drop_date = NULL
   FROM new_chars n
      INNER JOIN data_column_chars d ON (
         n.table_groups_id = d.table_groups_id
         AND n.schema_name = d.schema_name
         AND n.table_name = d.table_name
         AND n.column_name = d.column_name
      )
   WHERE data_column_chars.table_id = d.table_id
      AND data_column_chars.column_name = d.column_name
   RETURNING data_column_chars.*, d.db_data_type as old_data_type
)
INSERT INTO data_structure_log (
   element_id,
   change_date,
   change,
   old_data_type,
   new_data_type
)
SELECT u.column_id,
   u.last_mod_date,
   'M',
   u.old_data_type,
   u.db_data_type
   FROM update_chars u
   WHERE u.old_data_type <> u.db_data_type;


-- Add new records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      column_name,
      position,
      general_type,
      column_type,
      db_data_type,
      run_date
   FROM stg_data_chars_updates
   WHERE table_groups_id = :TABLE_GROUPS_ID
),
inserted_records AS (
   INSERT INTO data_column_chars (
         table_groups_id,
         schema_name,
         table_name,
         table_id,
         column_name,
         ordinal_position,
         general_type,
         column_type,
         db_data_type,
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
      n.db_data_type,
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
   WHERE d.table_id IS NULL
   RETURNING data_column_chars.*
)
INSERT INTO data_structure_log (
   element_id,
   change_date,
   change,
   new_data_type
)
SELECT i.column_id,
   i.add_date,
   'A',
   i.db_data_type
   FROM inserted_records i;

-- Mark dropped records
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      column_name
   FROM stg_data_chars_updates
   WHERE table_groups_id = :TABLE_GROUPS_ID
),
last_run AS (
   SELECT table_groups_id,
      MAX(run_date) as last_run_date
   FROM stg_data_chars_updates
   WHERE table_groups_id = :TABLE_GROUPS_ID
   GROUP BY table_groups_id
),
deleted_records AS (
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
      AND n.column_name IS NULL
   RETURNING data_column_chars.*
)
INSERT INTO data_structure_log (
   element_id,
   change_date,
   change,
   old_data_type
)
SELECT del.column_id,
   del.drop_date,
   'D',
   del.db_data_type
   FROM deleted_records del;
