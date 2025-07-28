SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_definitions
   ADD COLUMN history_calculation VARCHAR(20),
   ADD COLUMN history_lookback    INTEGER;

ALTER TABLE test_results
   ADD COLUMN result_signal VARCHAR(1000);