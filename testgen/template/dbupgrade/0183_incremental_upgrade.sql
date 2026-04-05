SET SEARCH_PATH TO {SCHEMA_NAME};

-- Allow individual test suites to be excluded from the table group's data contract.
-- Default TRUE preserves existing behaviour: all suites are included unless opted out.
ALTER TABLE test_suites
    ADD COLUMN IF NOT EXISTS include_in_contract BOOLEAN NOT NULL DEFAULT TRUE;
