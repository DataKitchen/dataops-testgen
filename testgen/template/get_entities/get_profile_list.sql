/*profile-list: project-code, connection-id
Output: list of all profiling runs conducted from profiling_runs
Optional: table-name*/

SELECT p.id as profile_run_id,
       p.project_code as project_key,
       schema_name, p.table_groups_id,
       profiling_starttime as start_time, status,
       COUNT(DISTINCT table_name) as tables,
       COUNT(DISTINCT table_name || '.' || column_name) as columns
  FROM profiling_runs p
INNER JOIN profile_results r
   ON (p.id = r.profile_run_id)
 WHERE p.table_groups_id = '{TABLE_GROUPS_ID}'::UUID
GROUP BY p.id, p.project_code, p.connection_id, schema_name, p.table_groups_id,
       profiling_starttime, status
ORDER BY profiling_starttime DESC;
