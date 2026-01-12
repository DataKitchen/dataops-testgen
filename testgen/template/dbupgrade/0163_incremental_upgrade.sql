SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE stg_test_definition_updates (
    test_suite_id      UUID,
    test_definition_id UUID,
    run_date           TIMESTAMP,
    lower_tolerance    VARCHAR(1000),
    upper_tolerance    VARCHAR(1000),
    prediction         JSONB
);

ALTER TABLE test_definitions
    ALTER COLUMN history_calculation TYPE VARCHAR(1000),
    ADD COLUMN history_calculation_upper VARCHAR(1000),
    ADD COLUMN prediction JSONB;

ALTER TABLE test_suites
    ADD COLUMN predict_sensitivity VARCHAR(6),
    ADD COLUMN predict_min_lookback INTEGER;
