SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE IF NOT EXISTS notification_destinations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code VARCHAR(30) NOT NULL,
    name VARCHAR(100) NOT NULL,
    destination_type VARCHAR(20) NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    secrets BYTEA NULL,

    CONSTRAINT fk_notification_destinations_project
        FOREIGN KEY (project_code)
        REFERENCES projects (project_code)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_notification_destinations_project_name
    ON notification_destinations (project_code, LOWER(name));

ALTER TABLE notification_settings
    ADD COLUMN IF NOT EXISTS notification_destination_id UUID NULL DEFAULT NULL;

-- Drop rows that would violate the addressing invariant added below: an empty
-- recipients list with no destination is a rule that never fires (the handlers
-- iterate .recipients and would send to nobody). Save-path validation rejects
-- this shape, so any row present here was written by a bypass and is
-- functionally dead.
DELETE FROM notification_settings
WHERE notification_destination_id IS NULL
  AND jsonb_array_length(recipients) = 0;

DO $$
BEGIN
    -- ``pg_constraint`` is database-wide, not schema-scoped. Without the
    -- ``conrelid`` predicate this finds a same-named constraint in ANY schema
    -- and skips creating this one, while the upgrade still reports success --
    -- and TG_METADATA_DB_SCHEMA makes several TestGen schemas in one database a
    -- supported deployment. ``::regclass`` resolves through the SEARCH_PATH set
    -- at the top of this file. Matches the guard shape in 0188.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_notification_settings_destination'
          AND conrelid = 'notification_settings'::regclass
    ) THEN
        ALTER TABLE notification_settings
            ADD CONSTRAINT fk_notification_settings_destination
                FOREIGN KEY (notification_destination_id)
                REFERENCES notification_destinations (id)
                ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_notification_settings_addressing'
          AND conrelid = 'notification_settings'::regclass
    ) THEN
        ALTER TABLE notification_settings
            ADD CONSTRAINT ck_notification_settings_addressing
                CHECK ((notification_destination_id IS NULL) <> (jsonb_array_length(recipients) = 0));
    END IF;
END $$;
