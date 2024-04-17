/*profile-info: project-code, connection-id
Output: latest profiling details
Optional: run_date (==profiling-run-id==), table-name, column-name, date-from, date-thru*/

SELECT profile_run_id,
       run_date,
       schema_name,
       table_name,
--        position,
       column_name,
       general_type,
       column_type,
       functional_data_type
  FROM profile_results
 WHERE table_name ILIKE '{TABLE_NAME}'
   AND profile_run_id = '{PROFILE_RUN}'::UUID
 ORDER BY table_name, position;