SET SEARCH_PATH TO {SCHEMA_NAME};

-- Schema-name matching in the SQL Server DDF query is now case-sensitive,
-- consistent with TestGen's case-sensitive joins and the other flavors. 
-- A case-insensitive source previously accepted a table
-- group whose configured schema name differed in case from the database;
-- such a group would now match no tables on its next profiling run.
--
-- data_table_chars.schema_name holds the case the source database actually
-- reported (it is populated from the DDF's c.table_schema, not the entered
-- value), so realign table_group_schema to that case. Guards:
--   * only mssql connections -- the DDF change was made only for that flavor,
--   * only when the catalog reports a single unambiguous schema for the group,
--   * only a case-only difference (LOWER() match), never a different schema,
--   * '<>' is case-sensitive in PostgreSQL, so correct rows are left untouched.
-- After this, the group's next profiling run stamps profile_results with the
-- corrected case, realigning the case-sensitive downstream joins.
UPDATE table_groups tg
SET table_group_schema = actual.schema_name
FROM (
    SELECT table_groups_id, MIN(schema_name) AS schema_name
    FROM data_table_chars
    WHERE drop_date IS NULL
    GROUP BY table_groups_id
    HAVING COUNT(DISTINCT schema_name) = 1
) actual
WHERE actual.table_groups_id = tg.id
  AND tg.table_group_schema <> actual.schema_name
  AND LOWER(tg.table_group_schema) = LOWER(actual.schema_name)
  AND EXISTS (
      SELECT 1 FROM connections cn
      WHERE cn.connection_id = tg.connection_id
        AND cn.sql_flavor = 'mssql'
  );
