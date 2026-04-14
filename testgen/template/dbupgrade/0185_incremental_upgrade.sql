SET SEARCH_PATH TO {SCHEMA_NAME};

-- Contract snapshot suite support

ALTER TABLE {SCHEMA_NAME}.test_suites
    ADD COLUMN IF NOT EXISTS is_contract_snapshot BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE {SCHEMA_NAME}.data_contracts
    ADD COLUMN IF NOT EXISTS snapshot_suite_id UUID
        REFERENCES {SCHEMA_NAME}.test_suites(id) ON DELETE SET NULL;

ALTER TABLE {SCHEMA_NAME}.test_definitions
    ADD COLUMN IF NOT EXISTS source_test_definition_id UUID;
