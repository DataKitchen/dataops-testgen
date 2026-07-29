-- Only this run's rows get the classification staged for this run.
UPDATE profile_results
   SET functional_table_type = COALESCE(s.table_period)||'-'||COALESCE(s.table_type)
FROM stg_functional_table_updates s
WHERE s.project_code = profile_results.project_code
  AND s.schema_name = profile_results.schema_name
  AND s.table_name = profile_results.table_name
  AND s.run_date = :RUN_DATE
  AND profile_results.profile_run_id = :PROFILE_RUN_ID;

--- Update table characteristics ---

-- Scoped to this run. Reading the table group's whole history instead produced one row per
-- distinct functional_table_type a table had ever been assigned, and UPDATE ... FROM with
-- several matching rows picks one arbitrarily -- so a table whose classification had ever
-- changed got a nondeterministic value here.
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
