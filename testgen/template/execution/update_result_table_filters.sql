UPDATE test_results
SET table_filter = filters.table_filter,
    match_table_filter = filters.match_table_filter
FROM jsonb_to_recordset(CAST(:TABLE_FILTERS AS JSONB)) AS filters(
    test_definition_id UUID,
    table_filter VARCHAR,
    match_table_filter VARCHAR
)
WHERE test_results.test_run_id = :TEST_RUN_ID
  AND test_results.test_definition_id = filters.test_definition_id;
