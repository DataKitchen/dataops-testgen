DELETE FROM stg_data_chars_updates
WHERE table_groups_id = :TABLE_GROUPS_ID
    AND refresh_id = :REFRESH_ID;
