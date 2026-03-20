SELECT DISTINCT dtc.table_name
FROM data_table_chars dtc
WHERE dtc.table_groups_id = :TABLE_GROUPS_ID ::UUID
    AND dtc.drop_date IS NULL
    AND dtc.table_name NOT IN (
        SELECT table_name
        FROM test_definitions
        WHERE test_suite_id = :TEST_SUITE_ID ::UUID
            AND test_type = 'Freshness_Trend'
    );
