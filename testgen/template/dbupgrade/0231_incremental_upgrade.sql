SET SEARCH_PATH TO {SCHEMA_NAME};

-- Exact sum of an integer or exact-decimal column, the baseline for an exact Match Sum
ALTER TABLE profile_results
    ADD COLUMN IF NOT EXISTS sum_value NUMERIC(38, 8);

-- Suites that existed before this setting keep deactivating tests that fail validation.
-- The column is added without a default so existing rows stay NULL and get TRUE; the IS NULL
-- filter keeps a re-run from overwriting user changes.
ALTER TABLE test_suites
    ADD COLUMN IF NOT EXISTS deactivate_invalid_tests BOOLEAN;

UPDATE test_suites
   SET deactivate_invalid_tests = TRUE
 WHERE deactivate_invalid_tests IS NULL;

ALTER TABLE test_suites
    ALTER COLUMN deactivate_invalid_tests SET DEFAULT FALSE,
    ALTER COLUMN deactivate_invalid_tests SET NOT NULL;

-- General types a column-scope test type works on; NULL means any
ALTER TABLE test_types
    ADD COLUMN IF NOT EXISTS column_general_types VARCHAR[];
