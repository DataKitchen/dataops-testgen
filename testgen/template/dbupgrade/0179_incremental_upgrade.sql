SET SEARCH_PATH TO {SCHEMA_NAME};

-- Hash existing fingerprint values for Table_Freshness tests
-- lower_tolerance stores the last computed fingerprint used for comparison
UPDATE test_definitions
   SET lower_tolerance = MD5(lower_tolerance)
 WHERE test_type = 'Table_Freshness'
   AND lower_tolerance IS NOT NULL
   AND LENGTH(lower_tolerance) <> 32;

-- Hash existing fingerprint values for Freshness_Trend monitors
-- baseline_value stores the fingerprint at the last detected table change
UPDATE test_definitions
   SET baseline_value = MD5(baseline_value)
 WHERE test_type = 'Freshness_Trend'
   AND baseline_value IS NOT NULL
   AND LENGTH(baseline_value) <> 32;

-- Hash existing result_signal values for Table_Freshness test results
UPDATE test_results
   SET result_signal = MD5(result_signal)
 WHERE test_type = 'Table_Freshness'
   AND result_signal IS NOT NULL
   AND LENGTH(result_signal) <> 32;

-- Hash existing result_measure values for Freshness_Trend test results
UPDATE test_results
   SET result_measure = MD5(result_measure)
 WHERE test_type = 'Freshness_Trend'
   AND result_measure IS NOT NULL
   AND LENGTH(result_measure) <> 32;
