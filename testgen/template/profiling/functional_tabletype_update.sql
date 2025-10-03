UPDATE profile_results
   SET functional_table_type = COALESCE(s.table_period)||'-'||COALESCE(s.table_type)
FROM stg_functional_table_updates s
WHERE s.project_code = profile_results.project_code
  AND s.schema_name = profile_results.schema_name
  AND s.table_name = profile_results.table_name
  AND s.run_date = profile_results.run_date
  AND s.run_date = :RUN_DATE;

--- Update table characteristics ---

WITH new_chars AS (
   SELECT table_groups_id,
      schema_name,
      table_name,
      functional_table_type
   FROM profile_results
   WHERE table_groups_id = :TABLE_GROUPS_ID
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
