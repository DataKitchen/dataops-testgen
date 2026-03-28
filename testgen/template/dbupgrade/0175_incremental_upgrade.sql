SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_definitions
    ADD COLUMN IF NOT EXISTS flagged BOOLEAN DEFAULT FALSE NOT NULL;

CREATE TABLE IF NOT EXISTS test_definition_notes (
   id                   UUID DEFAULT gen_random_uuid() PRIMARY KEY,
   test_definition_id   UUID NOT NULL REFERENCES test_definitions ON DELETE CASCADE,
   detail               TEXT NOT NULL,
   created_by           VARCHAR(100) NOT NULL,
   created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
   updated_at           TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_tdn_tdid ON test_definition_notes(test_definition_id, created_at DESC);
