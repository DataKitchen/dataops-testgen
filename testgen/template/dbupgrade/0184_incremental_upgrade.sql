SET SEARCH_PATH TO {SCHEMA_NAME};

-- Versioned contract snapshots
CREATE TABLE IF NOT EXISTS data_contracts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    table_group_id  UUID        NOT NULL REFERENCES table_groups(id) ON DELETE CASCADE,
    version         INTEGER     NOT NULL,
    saved_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    label           TEXT,
    contract_yaml   TEXT        NOT NULL,
    UNIQUE (table_group_id, version)
);

CREATE INDEX IF NOT EXISTS idx_data_contracts_tg_version
    ON data_contracts (table_group_id, version DESC);

-- Staleness tracking on table_groups
ALTER TABLE table_groups
    ADD COLUMN IF NOT EXISTS contract_stale           BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS last_contract_save_date  TIMESTAMPTZ;

-- The contract_version (VARCHAR) and contract_status columns added in 0180
-- are superseded by data_contracts.version and are no longer used.
COMMENT ON COLUMN table_groups.contract_version IS 'DEPRECATED — use data_contracts.version';
COMMENT ON COLUMN table_groups.contract_status  IS 'DEPRECATED — unused in versioned model';
