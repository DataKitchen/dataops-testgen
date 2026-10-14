SET SEARCH_PATH TO {SCHEMA_NAME};

-- Profile measures a test type or hygiene issue needs measured exactly; NULL means none
ALTER TABLE test_types
    ADD COLUMN IF NOT EXISTS exact_measures VARCHAR[];

ALTER TABLE profile_anomaly_types
    ADD COLUMN IF NOT EXISTS exact_measures VARCHAR[];
