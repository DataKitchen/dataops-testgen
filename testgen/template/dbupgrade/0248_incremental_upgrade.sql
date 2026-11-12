SET SEARCH_PATH TO {SCHEMA_NAME};

DROP INDEX IF EXISTS test_suites_name_unique;

UPDATE test_suites SET suite_type = 'standard' WHERE suite_type = 'regular';

ALTER TABLE test_suites ALTER COLUMN suite_type SET DEFAULT 'standard';

CREATE UNIQUE INDEX test_suites_name_unique
    ON test_suites (project_code, test_suite)
    WHERE suite_type IN ('standard', 'contract');
