SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE job_schedules (
    id UUID NOT NULL PRIMARY KEY,
    project_code VARCHAR(30) NOT NULL,
    key VARCHAR(100) NOT NULL,
    args JSONB NOT NULL,
    kwargs JSONB NOT NULL,
    cron_expr VARCHAR(50) NOT NULL,
    cron_tz VARCHAR(30) NOT NULL,
    UNIQUE (project_code, key, args, kwargs, cron_expr, cron_tz)
);

CREATE INDEX job_schedules_idx ON job_schedules (project_code, key);
