-- Fingerprint-change events from Freshness_Trend tests, used as secondary data for
-- freshness-gated SARIMAX prediction of Volume_Trend / Metric_Trend.
--
-- Returns one row per detected fingerprint change (result_signal = '0'), ordered by
-- (schema, table, time).
SELECT DISTINCT
  d.schema_name,
  d.table_name,
  r.test_run_id,
  r.test_time
FROM test_results r
JOIN test_definitions d ON d.id = r.test_definition_id
WHERE r.test_suite_id = :TEST_SUITE_ID
  AND d.test_suite_id = :TEST_SUITE_ID
  AND d.test_type = 'Freshness_Trend'
  AND d.test_active = 'Y'
  AND r.result_signal = '0'
ORDER BY d.schema_name, d.table_name, r.test_time;
