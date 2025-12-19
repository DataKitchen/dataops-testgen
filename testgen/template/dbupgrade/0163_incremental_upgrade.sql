SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_definitions
    ALTER COLUMN history_calculation TYPE VARCHAR(1000),
    ADD COLUMN history_calculation_upper VARCHAR(1000);
