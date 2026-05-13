-- Latest Freshness_Trend result_signal for a given table within the current run. Used
-- by Volume_Trend / Metric_Trend execution to detect whether the table has been updated
-- this run: result_signal = '0' means fingerprint changed, any other value means no
-- change (signal carries the interval-since-last-update).
SELECT result_signal
FROM test_results
WHERE test_run_id = :TEST_RUN_ID ::UUID
  AND test_type = 'Freshness_Trend'
  AND schema_name = :SCHEMA_NAME
  AND table_name = :TABLE_NAME
ORDER BY test_time DESC
LIMIT 1;
