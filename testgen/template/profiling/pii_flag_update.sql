-- Propagate pii_flag from profile_results to data_column_chars
-- Clears existing flags first, then sets flags from the latest profiling run
UPDATE data_column_chars
   SET pii_flag = NULL
 WHERE table_groups_id = :TABLE_GROUPS_ID;

WITH pii_selects
   AS ( SELECT table_groups_id, schema_name, table_name, column_name, pii_flag
          FROM profile_results
         WHERE profile_run_id = :PROFILE_RUN_ID
           AND pii_flag IS NOT NULL )
UPDATE data_column_chars
   SET pii_flag = pii_selects.pii_flag
  FROM pii_selects
 WHERE data_column_chars.table_groups_id = pii_selects.table_groups_id
   AND data_column_chars.schema_name = pii_selects.schema_name
   AND data_column_chars.table_name = pii_selects.table_name
   AND data_column_chars.column_name = pii_selects.column_name;
