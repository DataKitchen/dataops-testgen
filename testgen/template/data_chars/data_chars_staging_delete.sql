DELETE FROM stg_data_chars_updates
WHERE project_code = :PROJECT_CODE
    AND table_groups_id = :TABLE_GROUPS_ID
    AND run_date = :RUN_DATE;
