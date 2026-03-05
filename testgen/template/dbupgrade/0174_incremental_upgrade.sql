SET SEARCH_PATH TO {SCHEMA_NAME};

-- =============================================================================
-- Create project_memberships table
-- =============================================================================

CREATE TABLE IF NOT EXISTS project_memberships (
    id UUID DEFAULT gen_random_uuid()
        CONSTRAINT pk_project_memberships_id
            PRIMARY KEY,
    user_id UUID NOT NULL
        CONSTRAINT fk_project_memberships_auth_users
            REFERENCES auth_users(id)
            ON DELETE CASCADE,
    project_code VARCHAR(30) NOT NULL
        CONSTRAINT fk_project_memberships_projects
            REFERENCES projects(project_code)
            ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_project_memberships_user_project
        UNIQUE (user_id, project_code)
);

CREATE INDEX IF NOT EXISTS ix_pm_user_id ON project_memberships(user_id);
CREATE INDEX IF NOT EXISTS ix_pm_project_code ON project_memberships(project_code);
CREATE INDEX IF NOT EXISTS ix_pm_role ON project_memberships(role);

-- =============================================================================
-- Add is_global_admin column to auth_users
-- =============================================================================

ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS is_global_admin BOOLEAN NOT NULL DEFAULT FALSE;

-- =============================================================================
-- Set is_global_admin = TRUE for users with role = 'admin'
-- =============================================================================

UPDATE auth_users SET is_global_admin = TRUE WHERE role = 'admin';

-- =============================================================================
-- Migrate ALL users to project_memberships
-- Each user gets their current role in every existing project
-- =============================================================================

INSERT INTO project_memberships (user_id, project_code, role)
SELECT
    u.id AS user_id,
    p.project_code AS project_code,
    u.role AS role
FROM auth_users u
CROSS JOIN projects p
ON CONFLICT (user_id, project_code) DO NOTHING;

-- =============================================================================
-- Drop the role column from auth_users
-- =============================================================================

ALTER TABLE auth_users DROP COLUMN IF EXISTS role;
