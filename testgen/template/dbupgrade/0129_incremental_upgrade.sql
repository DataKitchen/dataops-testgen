SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE IF NOT EXISTS score_definition_results_history (
    definition_id     UUID                        CONSTRAINT score_definitions_filters_score_definitions_definition_id_fk
                                                    REFERENCES score_definitions (id)
                                                    ON DELETE CASCADE,
    category          TEXT                        NOT NULL,
    score             DOUBLE PRECISION            DEFAULT NULL,
    test_run_id       UUID                        DEFAULT NULL,
    profiling_run_id  UUID                        DEFAULT NULL,
    last_run_time     TIMESTAMP WITH TIME ZONE    NOT NULL
);
