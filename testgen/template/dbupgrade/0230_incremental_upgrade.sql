SET SEARCH_PATH TO {SCHEMA_NAME};

-- A catalogued table or column is identified by (table_groups_id, table_name[, column_name]).
--
-- A catalog written while schema_name formed part of that identity can hold more than one row per
-- identity. Saving a table group writes its catalog, while the schema stays editable until the
-- group has a test suite or a profiling run, so a save under one schema followed by a save under
-- another leaves the first rows behind marked dropped. Reads that join on the identity alone match
-- every one of them and multiply.
--
-- The survivor is the row a catalog refresh resolves to: live before dropped, then the lowest id.
-- Losing rows hand their columns and their log entries over before they go, because nothing
-- references table_id or column_id by constraint and a dangling one would fail silently.

-- Columns follow their table to the surviving row.
UPDATE data_column_chars c
   SET table_id = k.keeper_id
  FROM (
     SELECT d.table_id AS loser_id, s.table_id AS keeper_id
       FROM data_table_chars d
       JOIN (
          SELECT DISTINCT ON (table_groups_id, table_name) table_groups_id, table_name, table_id
            FROM data_table_chars
           ORDER BY table_groups_id, table_name, (drop_date IS NOT NULL), table_id
       ) s
         ON d.table_groups_id = s.table_groups_id
        AND d.table_name = s.table_name
      WHERE d.table_id <> s.table_id
  ) k
 WHERE c.table_id = k.loser_id;

UPDATE data_structure_log l
   SET table_id = k.keeper_id
  FROM (
     SELECT d.table_id AS loser_id, s.table_id AS keeper_id
       FROM data_table_chars d
       JOIN (
          SELECT DISTINCT ON (table_groups_id, table_name) table_groups_id, table_name, table_id
            FROM data_table_chars
           ORDER BY table_groups_id, table_name, (drop_date IS NOT NULL), table_id
       ) s
         ON d.table_groups_id = s.table_groups_id
        AND d.table_name = s.table_name
      WHERE d.table_id <> s.table_id
  ) k
 WHERE l.table_id = k.loser_id;

DELETE FROM data_table_chars d
 USING (
    SELECT DISTINCT ON (table_groups_id, table_name) table_groups_id, table_name, table_id
      FROM data_table_chars
     ORDER BY table_groups_id, table_name, (drop_date IS NOT NULL), table_id
 ) s
 WHERE d.table_groups_id = s.table_groups_id
   AND d.table_name = s.table_name
   AND d.table_id <> s.table_id;

-- The same identity collapse one level down, now that every column names a surviving table.
UPDATE data_structure_log l
   SET column_id = k.keeper_id
  FROM (
     SELECT c.column_id AS loser_id, s.column_id AS keeper_id
       FROM data_column_chars c
       JOIN (
          SELECT DISTINCT ON (table_groups_id, table_name, column_name)
                 table_groups_id, table_name, column_name, column_id
            FROM data_column_chars
           ORDER BY table_groups_id, table_name, column_name, (drop_date IS NOT NULL), column_id
       ) s
         ON c.table_groups_id = s.table_groups_id
        AND c.table_name = s.table_name
        AND c.column_name = s.column_name
      WHERE c.column_id <> s.column_id
  ) k
 WHERE l.column_id = k.loser_id;

DELETE FROM data_column_chars c
 USING (
    SELECT DISTINCT ON (table_groups_id, table_name, column_name)
           table_groups_id, table_name, column_name, column_id
      FROM data_column_chars
     ORDER BY table_groups_id, table_name, column_name, (drop_date IS NOT NULL), column_id
 ) s
 WHERE c.table_groups_id = s.table_groups_id
   AND c.table_name = s.table_name
   AND c.column_name = s.column_name
   AND c.column_id <> s.column_id;

-- Keyed on the identity the catalog is read by, and unique so a write that would reintroduce a
-- second row fails where it happens instead of multiplying rows in every later read.
DROP INDEX IF EXISTS idx_dtc_tg_schema_table;
DROP INDEX IF EXISTS idx_dcc_tg_schema_table_column;

CREATE UNIQUE INDEX IF NOT EXISTS uix_dtc_tg_table
  ON data_table_chars (table_groups_id, table_name);

CREATE UNIQUE INDEX IF NOT EXISTS uix_dcc_tg_table_column
  ON data_column_chars (table_groups_id, table_name, column_name);
