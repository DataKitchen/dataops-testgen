SET SEARCH_PATH TO {SCHEMA_NAME};

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = '{SCHEMA_NAME}'
          AND table_name = 'auth_users'
          AND column_name = 'preferences'
    ) THEN
        ALTER TABLE auth_users
            ADD COLUMN preferences JSONB NOT NULL DEFAULT '{}';
    END IF;
END $$;
