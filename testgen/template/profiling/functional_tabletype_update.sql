-- Source and target are both keyed on the run. stg_functional_table_updates carries no table
-- group, and two table groups of one project over the same schema stage the same
-- (project_code, schema_name, table_name), so the run id is what selects this run's rows.
UPDATE profile_results
   SET functional_table_type = COALESCE(s.table_period)||'-'||COALESCE(s.table_type)
FROM stg_functional_table_updates s
WHERE s.project_code = profile_results.project_code
  AND s.schema_name = profile_results.schema_name
  AND s.table_name = profile_results.table_name
  AND s.profile_run_id = :PROFILE_RUN_ID
  AND profile_results.profile_run_id = :PROFILE_RUN_ID;

--- Update table characteristics ---

-- Scoped to this run: over the table group's whole history a table has one row per
-- functional_table_type it has ever been assigned, and UPDATE ... FROM picks arbitrarily among
-- several matching source rows.
WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      functional_table_type
   FROM profile_results
   WHERE profile_run_id = :PROFILE_RUN_ID
   GROUP BY table_groups_id,
      schema_name,
      table_name,
      functional_table_type
)
UPDATE data_table_chars
SET functional_table_type = COALESCE(n.functional_table_type, d.functional_table_type)
FROM new_chars n
   INNER JOIN data_table_chars d ON (
      n.table_groups_id = d.table_groups_id
      AND n.schema_name = d.schema_name
      AND n.table_name = d.table_name
   )
WHERE data_table_chars.table_id = d.table_id;
