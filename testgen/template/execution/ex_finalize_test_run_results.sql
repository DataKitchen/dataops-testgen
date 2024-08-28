UPDATE test_results
   SET test_description = COALESCE(r.test_description, d.test_description, tt.test_description),
       severity = COALESCE(d.severity, s.severity, tt.default_severity),
       threshold_value = COALESCE(r.threshold_value, d.threshold_value),
       result_status = CASE
                         WHEN r.result_code = 1 THEN 'Passed'
                         WHEN r.result_code = 0
                          AND COALESCE(d.severity, s.severity, tt.default_severity) = 'Warning' THEN 'Warning'
                         WHEN r.result_code = 0
                          AND COALESCE(d.severity, s.severity, tt.default_severity) = 'Fail' THEN 'Failed'
                         WHEN r.result_code = 0 THEN 'Warning'
                       END,
       observability_status = CASE
                                WHEN r.observability_status = 'Sent' THEN 'Sent'
                                WHEN COALESCE(d.export_to_observability, s.export_to_observability) = 'Y' THEN 'Queued'
                                WHEN COALESCE(d.export_to_observability, s.export_to_observability) = 'N' THEN 'Ignore'
                              END,
       result_message = COALESCE(r.result_message,
                                 tt.measure_uom || ': ' || r.result_measure::VARCHAR
                                  || ', Threshold: ' || d.threshold_value::VARCHAR
                                  || CASE
                                       WHEN r.skip_errors > 0 THEN 'Errors Ignored: ' || r.skip_errors::VARCHAR
                                       ELSE ''
                                     END),
      table_groups_id = d.table_groups_id,
      test_suite_id = s.id,
      auto_gen = d.last_auto_gen_date IS NOT NULL
  FROM test_results r
INNER JOIN test_suites s ON r.test_suite_id = s.id
INNER JOIN test_definitions d ON r.test_definition_id = d.id
INNER JOIN test_types tt ON r.test_type = tt.test_type
WHERE r.test_run_id = '{TEST_RUN_ID}'
  AND test_results.id = r.id;
