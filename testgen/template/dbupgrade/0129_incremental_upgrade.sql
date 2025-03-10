SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE IF NOT EXISTS score_definition_results_history (
    definition_id     UUID                        CONSTRAINT score_definitions_filters_score_definitions_definition_id_fk
                                                    REFERENCES score_definitions (id)
                                                    ON DELETE CASCADE,
    category          TEXT                        NOT NULL,
    score             DOUBLE PRECISION            DEFAULT NULL,
    last_run_time     TIMESTAMP                   NOT NULL
);

CREATE INDEX sdrh_def_last_run
   ON score_definition_results_history(definition_id, last_run_time);
