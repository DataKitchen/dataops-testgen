SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE IF NOT EXISTS score_definitions (
   id               UUID          DEFAULT gen_random_uuid() PRIMARY KEY,
   project_code     VARCHAR(30)   CONSTRAINT score_definitions_projects_project_code_fk
                                            REFERENCES projects (project_code)
                                            ON DELETE CASCADE,

  name              VARCHAR(100)  NOT NULL,
  total_score       BOOLEAN       NOT NULL DEFAULT true,
  cde_score         BOOLEAN       NOT NULL DEFAULT true,
  category          VARCHAR(30)   DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS score_definition_filters (
    id              UUID         DEFAULT gen_random_uuid() PRIMARY KEY,
    definition_id   UUID         CONSTRAINT score_definitions_filters_score_definitions_definition_id_fk
                                    REFERENCES score_definitions (id)
                                    ON DELETE CASCADE,
    field           TEXT         DEFAULT NULL,
    value           TEXT         DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS score_definition_results (
    definition_id   UUID                CONSTRAINT score_definitions_filters_score_definitions_definition_id_fk
                                            REFERENCES score_definitions (id)
                                            ON DELETE CASCADE,
    category        TEXT                NOT NULL,
    score           DOUBLE PRECISION    DEFAULT NULL
);