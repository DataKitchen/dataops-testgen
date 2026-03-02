SET SEARCH_PATH TO {SCHEMA_NAME};

INSERT INTO projects
    (project_code, project_name, observability_api_key, observability_api_url)
SELECT '{PROJECT_CODE}' as project_code,
       '{PROJECT_NAME}' as project_name,
       '{OBSERVABILITY_API_KEY}' as observability_api_key,
       '{OBSERVABILITY_API_URL}' as observability_api_url;


WITH inserted_user AS (
    INSERT INTO auth_users
        (username, email, name, password, is_global_admin)
    SELECT
        '{UI_USER_USERNAME}' as username,
        '{UI_USER_EMAIL}' as email,
        '{UI_USER_NAME}' as name,
        '{UI_USER_ENCRYPTED_PASSWORD}' as password,
        true as is_global_admin
    RETURNING id
)
INSERT INTO project_memberships
    (user_id, project_code, role, created_at)
SELECT id AS user_id,
    '{PROJECT_CODE}' AS project_code,
    'admin' AS role,
    NOW() AS created_at
FROM inserted_user;
