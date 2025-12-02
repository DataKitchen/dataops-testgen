DELETE FROM stg_data_chars_updates
WHERE table_groups_id = :TABLE_GROUPS_ID
    AND run_date = :RUN_DATE;
