SET SEARCH_PATH TO {SCHEMA_NAME};

-- OAuth2 clients (MCP apps, automation scripts)
CREATE TABLE IF NOT EXISTS oauth2_clients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES auth_users(id) ON DELETE SET NULL,
    client_id       VARCHAR(48) NOT NULL UNIQUE,
    client_secret   VARCHAR(120),
    client_id_issued_at     INTEGER NOT NULL DEFAULT 0,
    client_secret_expires_at INTEGER NOT NULL DEFAULT 0,
    client_metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_oauth2_clients_client_id ON oauth2_clients(client_id);

-- OAuth2 authorization codes (temporary, single-use)
CREATE TABLE IF NOT EXISTS oauth2_authorization_codes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    code            VARCHAR(120) NOT NULL UNIQUE,
    client_id       VARCHAR(48) NOT NULL,
    redirect_uri    TEXT DEFAULT '',
    response_type   TEXT DEFAULT '',
    scope           TEXT DEFAULT '',
    nonce           TEXT,
    auth_time       INTEGER NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER,
    acr             TEXT,
    amr             TEXT,
    code_challenge  TEXT,
    code_challenge_method VARCHAR(48)
);

-- OAuth2 tokens (access + refresh)
CREATE TABLE IF NOT EXISTS oauth2_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES auth_users(id) ON DELETE CASCADE,
    client_id       VARCHAR(48) NOT NULL,
    token_type      VARCHAR(40),
    access_token    VARCHAR(2048) NOT NULL UNIQUE,
    refresh_token   VARCHAR(255),
    scope           TEXT DEFAULT '',
    issued_at       INTEGER NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW())::INTEGER,
    access_token_revoked_at  INTEGER NOT NULL DEFAULT 0,
    refresh_token_revoked_at INTEGER NOT NULL DEFAULT 0,
    expires_in      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_oauth2_tokens_refresh_token ON oauth2_tokens(refresh_token);
