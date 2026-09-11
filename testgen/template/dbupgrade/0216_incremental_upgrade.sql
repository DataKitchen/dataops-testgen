SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_suites
    ADD COLUMN IF NOT EXISTS suite_type VARCHAR(20) NOT NULL DEFAULT 'regular';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = '{SCHEMA_NAME}'
        AND table_name = 'test_suites'
        AND column_name = 'is_monitor'
    ) THEN
        UPDATE test_suites SET suite_type = 'monitor' WHERE is_monitor IS TRUE;
    END IF;
END $$;

ALTER TABLE test_suites DROP COLUMN IF EXISTS is_monitor;
