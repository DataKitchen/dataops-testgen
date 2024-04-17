SELECT p.profile_run_id,
       p.run_date,
       p.schema_name,
       p.table_name,
--        p."position",
       p.column_name,
       p.general_type,
       p.column_type,
       p.datatype_suggestion
FROM profile_results p
WHERE profile_run_id = '{PROFILE_RUN_ID}'::UUID
ORDER BY p.schema_name, p.table_name, p.position;
