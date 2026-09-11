SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE IF NOT EXISTS suite_versions (
   id                  UUID NOT NULL
      CONSTRAINT suite_versions_id_pk
         PRIMARY KEY,
   test_suite_id       UUID
      CONSTRAINT suite_versions_test_suites_fk
         REFERENCES test_suites ON DELETE CASCADE,
   version             INTEGER NOT NULL,
   metadata_document   JSONB,
   frozen_document     TEXT,
   frozen_at           TIMESTAMPTZ,
   odcs_api_version    VARCHAR(20),
   label               VARCHAR(100),
   created_by          VARCHAR(100),
   created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
   updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
   CONSTRAINT suite_versions_placeholder_shape CHECK (
      (id =  '00000000-0000-0000-0000-000000000000' AND test_suite_id IS NULL     AND frozen_at IS NOT NULL)
   OR (id <> '00000000-0000-0000-0000-000000000000' AND test_suite_id IS NOT NULL)),
   CONSTRAINT suite_versions_version_range CHECK (
      (test_suite_id IS NULL     AND version = 0)
   OR (test_suite_id IS NOT NULL AND version > 0))
);

CREATE UNIQUE INDEX IF NOT EXISTS uix_sv_suite_version
   ON suite_versions (test_suite_id, version);

CREATE UNIQUE INDEX IF NOT EXISTS uix_sv_one_draft
   ON suite_versions (test_suite_id)
   WHERE frozen_at IS NULL;

INSERT INTO suite_versions (id, test_suite_id, version, frozen_at)
VALUES ('00000000-0000-0000-0000-000000000000', NULL, 0, NOW())
ON CONFLICT (id) DO NOTHING;

ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS version_id UUID;
