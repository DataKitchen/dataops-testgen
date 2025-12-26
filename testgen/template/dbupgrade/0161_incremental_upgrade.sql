SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE notification_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code VARCHAR(30) NOT NULL,

    event VARCHAR(20) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    recipients JSONB NOT NULL DEFAULT '[]'::jsonb,

    test_suite_id UUID NULL DEFAULT NULL,
    table_group_id UUID NULL DEFAULT NULL,
    score_definition_id UUID NULL DEFAULT NULL,

    settings JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT fk_notification_settings_test_suite
        FOREIGN KEY (test_suite_id)
        REFERENCES test_suites (id)
        ON DELETE CASCADE,

    CONSTRAINT fk_notification_settings_table_group
        FOREIGN KEY (table_group_id)
        REFERENCES table_groups (id)
        ON DELETE CASCADE,

    CONSTRAINT fk_notification_settings_score_definition
        FOREIGN KEY (score_definition_id)
        REFERENCES score_definitions (id)
        ON DELETE CASCADE
);
