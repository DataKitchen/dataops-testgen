SET SEARCH_PATH TO {SCHEMA_NAME};

-- Add ODCS-aligned contract metadata fields to table_groups
ALTER TABLE table_groups
    ADD COLUMN IF NOT EXISTS contract_version VARCHAR(20),
    ADD COLUMN IF NOT EXISTS contract_status  VARCHAR(20) DEFAULT 'draft';
