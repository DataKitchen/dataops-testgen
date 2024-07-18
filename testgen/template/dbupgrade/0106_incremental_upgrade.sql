SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE connections ADD COLUMN connect_by_key BOOLEAN DEFAULT FALSE;
ALTER TABLE connections ADD COLUMN private_key BYTEA;
ALTER TABLE connections ADD COLUMN private_key_passphrase BYTEA;
