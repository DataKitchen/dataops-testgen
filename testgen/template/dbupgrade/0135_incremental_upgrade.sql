SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE job_schedules (
    id UUID NOT NULL PRIMARY KEY,
    project_code VARCHAR(30) NOT NULL,
    key VARCHAR(100) NOT NULL,
    args JSON NOT NULL,
    kwargs JSON NOT NULL,
    cron_expr VARCHAR(50) NOT NULL,
    cron_tz VARCHAR(30) NOT NULL
)
