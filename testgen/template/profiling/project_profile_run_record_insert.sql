INSERT INTO profiling_runs (id, project_code, connection_id, table_groups_id, profiling_starttime, process_id)
(SELECT '{PROFILE_RUN_ID}' :: UUID  as id,
        '{PROJECT_CODE}' as project_code,
         {CONNECTION_ID} as connection_id,
        '{TABLE_GROUPS_ID}' :: UUID as table_groups_id,
        '{RUN_DATE}' as profiling_starttime,
        '{PROCESS_ID}' as process_id
     );
