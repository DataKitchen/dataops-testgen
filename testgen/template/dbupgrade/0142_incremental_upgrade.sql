SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_definitions
  ADD COLUMN lower_tolerance VARCHAR(1000),
  ADD COLUMN upper_tolerance VARCHAR(1000);
