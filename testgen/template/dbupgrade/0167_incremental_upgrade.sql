SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_suites
    ADD COLUMN predict_exclude_weekends BOOLEAN DEFAULT FALSE,
    ADD COLUMN predict_holiday_codes VARCHAR(100);
