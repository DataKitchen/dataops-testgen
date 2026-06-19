SET SEARCH_PATH TO {SCHEMA_NAME};

-- Personal access tokens are stored as oauth2_tokens rows; the name labels each
-- one in the user's token list. NULL marks a non-PAT token (auth-code / MCP flows).
ALTER TABLE oauth2_tokens ADD COLUMN name VARCHAR(255);

-- Classify clients so personal-access-token clients are distinguishable from
-- dynamically-registered external clients (MCP apps, automation). Existing rows
-- all predate PATs and are externally registered, so they default to 'external'.
ALTER TABLE oauth2_clients ADD COLUMN client_type VARCHAR(20) NOT NULL DEFAULT 'external';

-- Drop the client owner: it was only ever read by the client-credentials grant
-- (removed). User identity now rides the token (oauth2_tokens.user_id + the JWT
-- username), so a client needs no owner. The FK constraint drops with the column.
ALTER TABLE oauth2_clients DROP COLUMN user_id;
