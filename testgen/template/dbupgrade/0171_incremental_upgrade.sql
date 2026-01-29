SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_suites
    ADD COLUMN monitor_regenerate_freshness BOOLEAN DEFAULT TRUE;
