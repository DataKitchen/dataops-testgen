SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_definitions
   ADD COLUMN IF NOT EXISTS version_id UUID NOT NULL
      DEFAULT '00000000-0000-0000-0000-000000000000';

DO $$
BEGIN
   IF NOT EXISTS (
      SELECT 1 FROM pg_constraint WHERE conname = 'test_definitions_version_fk'
   ) THEN
      ALTER TABLE test_definitions
         ADD CONSTRAINT test_definitions_version_fk
         FOREIGN KEY (version_id) REFERENCES suite_versions ON DELETE CASCADE NOT VALID;
   END IF;
END $$;

ALTER TABLE test_definitions VALIDATE CONSTRAINT test_definitions_version_fk;

ALTER TABLE test_definitions ADD COLUMN IF NOT EXISTS contract_term_id VARCHAR(100);

DROP INDEX IF EXISTS uix_td_autogen_schema;
CREATE UNIQUE INDEX uix_td_autogen_schema
   ON test_definitions (test_suite_id, version_id, test_type, schema_name)
   WHERE last_auto_gen_date IS NOT NULL
      AND table_name IS NULL
      AND column_name IS NULL;

DROP INDEX IF EXISTS uix_td_autogen_table;
CREATE UNIQUE INDEX uix_td_autogen_table
   ON test_definitions (test_suite_id, version_id, test_type, schema_name, table_name)
   WHERE last_auto_gen_date IS NOT NULL
      AND table_name IS NOT NULL
      AND column_name IS NULL;

DROP INDEX IF EXISTS uix_td_autogen_column;
CREATE UNIQUE INDEX uix_td_autogen_column
   ON test_definitions (test_suite_id, version_id, test_type, schema_name, table_name, column_name)
   WHERE last_auto_gen_date IS NOT NULL
      AND table_name IS NOT NULL
      AND column_name IS NOT NULL;

DROP INDEX IF EXISTS uix_td_external_id;
CREATE UNIQUE INDEX uix_td_external_id
   ON test_definitions (test_suite_id, version_id, external_id)
   WHERE external_id IS NOT NULL;

DROP INDEX IF EXISTS ix_td_ts_fk;
CREATE INDEX ix_td_ts_fk
   ON test_definitions (test_suite_id, version_id);

CREATE UNIQUE INDEX IF NOT EXISTS uix_td_contract_term
   ON test_definitions (version_id, contract_term_id)
   WHERE contract_term_id IS NOT NULL;
