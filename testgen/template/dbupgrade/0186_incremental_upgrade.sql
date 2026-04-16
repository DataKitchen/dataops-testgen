SET SEARCH_PATH TO {SCHEMA_NAME};

-- 1. Add is_contract_suite column to test_suites
ALTER TABLE {SCHEMA_NAME}.test_suites
    ADD COLUMN IF NOT EXISTS is_contract_suite BOOLEAN;

-- 2. Create contracts table
CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.contracts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,
    project_code     TEXT NOT NULL REFERENCES {SCHEMA_NAME}.projects(project_code),
    table_group_id   UUID NOT NULL REFERENCES {SCHEMA_NAME}.table_groups(id),
    test_suite_id    UUID NOT NULL REFERENCES {SCHEMA_NAME}.test_suites(id),
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (name, project_code),
    UNIQUE (test_suite_id)
);

-- 3. Create contract_versions table
CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.contract_versions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id       UUID NOT NULL REFERENCES {SCHEMA_NAME}.contracts(id) ON DELETE CASCADE,
    version           INT NOT NULL,
    is_current        BOOLEAN NOT NULL DEFAULT FALSE,
    saved_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    label             TEXT,
    contract_yaml     TEXT NOT NULL,
    term_count        INT NOT NULL DEFAULT 0,
    snapshot_suite_id UUID REFERENCES {SCHEMA_NAME}.test_suites(id) ON DELETE SET NULL,
    UNIQUE (contract_id, version)
);

-- 4. Partial unique index: exactly one is_current=TRUE per contract
CREATE UNIQUE INDEX IF NOT EXISTS contract_versions_one_current
    ON {SCHEMA_NAME}.contract_versions (contract_id)
    WHERE is_current = TRUE;
