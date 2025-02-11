SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE TABLE IF NOT EXISTS score_definition_results_breakdown (
    id                   UUID                DEFAULT gen_random_uuid() PRIMARY KEY,
    definition_id        UUID                CONSTRAINT score_definitions_filters_score_definitions_definition_id_fk
                                                REFERENCES score_definitions (id)
                                                ON DELETE CASCADE,
    category             TEXT                NOT NULL,
    score_type           TEXT                NOT NULL,
    table_groups_id      TEXT                DEFAULT NULL,
    table_name           TEXT                DEFAULT NULL,
    column_name          TEXT                DEFAULT NULL,
    dq_dimension         TEXT                DEFAULT NULL,
    semantic_data_type   TEXT                DEFAULT NULL,
    impact               DOUBLE PRECISION    DEFAULT 0.0,
    score                DOUBLE PRECISION    DEFAULT 0.0,
    issue_ct             INTEGER             DEFAULT 0
);

-- Results Breakdown by "table_name" for "score"
WITH
profiling_records AS (
    SELECT
        project_code,
        table_groups_id,
        table_groups_name,
        table_name,
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE NULLIF(table_name, '') IS NOT NULL
    GROUP BY project_code, table_groups_id, table_groups_name, table_name
),
test_records AS (
    SELECT
        project_code,
        table_groups_id,
        table_groups_name,
        table_name,
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_column
    WHERE NULLIF(table_name, '') IS NOT NULL
    GROUP BY project_code, table_groups_id, table_groups_name, table_name
),
parent AS (
    SELECT
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        COALESCE(profiling_records.table_groups_name, test_records.table_groups_name) AS table_groups_name,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code), COALESCE(profiling_records.table_groups_name, test_records.table_groups_name)
)
INSERT INTO score_definition_results_breakdown
SELECT id, definition_id, category, score_type, table_groups_id, table_name, column_name, dq_dimension, semantic_data_type, impact, score, issue_ct
FROM (
    SELECT
        gen_random_uuid() AS id,
        score_definitions.id AS definition_id,
        'table_name' AS category,
        'score' AS score_type,
        COALESCE(profiling_records.table_groups_id, test_records.table_groups_id) AS table_groups_id,
        COALESCE(profiling_records.table_name, test_records.table_name) AS table_name,
        NULL AS column_name,
        NULL AS dq_dimension,
        NULL AS semantic_data_type,
        100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) AS impact,
        (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
        (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct,
        row_number() OVER (PARTITION BY score_definitions.id ORDER BY 100 * (COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0) + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)) DESC)
    FROM profiling_records
    FULL OUTER JOIN test_records
        ON (test_records.project_code = profiling_records.project_code AND test_records.table_groups_id = profiling_records.table_groups_id AND test_records.table_name = profiling_records.table_name)
    INNER JOIN parent
        ON (
            (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
            AND (parent.table_groups_name = profiling_records.table_groups_name OR parent.table_groups_name = test_records.table_groups_name)
        )
    INNER JOIN score_definitions
        ON (
            (score_definitions.project_code = profiling_records.project_code OR score_definitions.project_code = test_records.project_code)
            AND (score_definitions.name = profiling_records.table_groups_name OR score_definitions.name = test_records.table_groups_name)
        )
) AS results
WHERE row_number <= 100;

-- Results Breakdown by "column_name" for "score"
WITH
profiling_records AS (
    SELECT
        project_code,
        table_groups_id,
        table_groups_name,
        table_name,
        column_name,
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE NULLIF(column_name, '') IS NOT NULL
    GROUP BY project_code, table_groups_id, table_groups_name, table_name, column_name
),
test_records AS (
    SELECT
        project_code,
        table_groups_id,
        table_groups_name,
        table_name,
        column_name,
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_column
    WHERE NULLIF(column_name, '') IS NOT NULL
    GROUP BY project_code, table_groups_id, table_groups_name, table_name, column_name
),
parent AS (
    SELECT
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        COALESCE(profiling_records.table_groups_name, test_records.table_groups_name) AS table_groups_name,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code), COALESCE(profiling_records.table_groups_name, test_records.table_groups_name)
)
INSERT INTO score_definition_results_breakdown
SELECT id, definition_id, category, score_type, table_groups_id, table_name, column_name, dq_dimension, semantic_data_type, impact, score, issue_ct
FROM (
    SELECT
        gen_random_uuid() AS id,
        score_definitions.id AS definition_id,
        'column_name' AS category,
        'score' AS score_type,
        COALESCE(profiling_records.table_groups_id, test_records.table_groups_id) AS table_groups_id,
        COALESCE(profiling_records.table_name, test_records.table_name) AS table_name,
        COALESCE(profiling_records.column_name, test_records.column_name) AS column_name,
        NULL AS dq_dimension,
        NULL AS semantic_data_type,
        100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) AS impact,
        (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
        (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct,
        row_number() OVER (PARTITION BY score_definitions.id ORDER BY 100 * (COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0) + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)) DESC)
    FROM profiling_records
    FULL OUTER JOIN test_records
        ON (test_records.project_code = profiling_records.project_code AND test_records.table_groups_id = profiling_records.table_groups_id AND test_records.table_name = profiling_records.table_name AND test_records.column_name = profiling_records.column_name)
    INNER JOIN parent
        ON (
            (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
            AND (parent.table_groups_name = profiling_records.table_groups_name OR parent.table_groups_name = test_records.table_groups_name)
        )
    INNER JOIN score_definitions
        ON (
            (score_definitions.project_code = profiling_records.project_code OR score_definitions.project_code = test_records.project_code)
            AND (score_definitions.name = profiling_records.table_groups_name OR score_definitions.name = test_records.table_groups_name)
        )
) AS results
WHERE row_number <= 100;

-- Results Breakdown by "dq_dimension" for "score"
WITH
profiling_records AS (
    SELECT
        project_code,
        table_groups_name,
        dq_dimension,
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_dimension
    WHERE NULLIF(dq_dimension, '') IS NOT NULL
    GROUP BY project_code, table_groups_name, dq_dimension
),
test_records AS (
    SELECT
        project_code,
        table_groups_name,
        dq_dimension,
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_dimension
    WHERE NULLIF(dq_dimension, '') IS NOT NULL
    GROUP BY project_code, table_groups_name, dq_dimension
),
parent AS (
    SELECT
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        COALESCE(profiling_records.table_groups_name, test_records.table_groups_name) AS table_groups_name,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code), COALESCE(profiling_records.table_groups_name, test_records.table_groups_name)
)
INSERT INTO score_definition_results_breakdown
SELECT id, definition_id, category, score_type, table_groups_id, table_name, column_name, dq_dimension, semantic_data_type, impact, score, issue_ct
FROM (
    SELECT
        gen_random_uuid() AS id,
        score_definitions.id AS definition_id,
        'dq_dimension' AS category,
        'score' AS score_type,
        NULL AS table_groups_id,
        NULL AS table_name,
        NULL AS column_name,
        COALESCE(profiling_records.dq_dimension, test_records.dq_dimension) AS dq_dimension,
        NULL AS semantic_data_type,
        100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) AS impact,
        (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
        (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct,
        row_number() OVER (PARTITION BY score_definitions.id ORDER BY 100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) DESC)
    FROM profiling_records
    FULL OUTER JOIN test_records
        ON (
            test_records.project_code = profiling_records.project_code
            AND test_records.dq_dimension = profiling_records.dq_dimension
            AND test_records.table_groups_name = profiling_records.table_groups_name
        )
    INNER JOIN parent
        ON (
            (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
            AND (parent.table_groups_name = profiling_records.table_groups_name OR parent.table_groups_name = test_records.table_groups_name)
        )
    INNER JOIN score_definitions
        ON (
            (score_definitions.project_code = profiling_records.project_code OR score_definitions.project_code = test_records.project_code)
            AND (score_definitions.name = profiling_records.table_groups_name OR score_definitions.name = test_records.table_groups_name)
        )
) AS results
WHERE row_number <= 100;

-- Results Breakdown by "semantic_data_type" for "score"
WITH
profiling_records AS (
    SELECT
        project_code,
        table_groups_name,
        semantic_data_type,
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE NULLIF(semantic_data_type, '') IS NOT NULL
    GROUP BY project_code, table_groups_name, semantic_data_type
),
test_records AS (
    SELECT
        project_code,
        table_groups_name,
        semantic_data_type,
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_column
    WHERE NULLIF(semantic_data_type, '') IS NOT NULL
    GROUP BY project_code, table_groups_name, semantic_data_type
),
parent AS (
    SELECT
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        COALESCE(profiling_records.table_groups_name, test_records.table_groups_name) AS table_groups_name,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code), COALESCE(profiling_records.table_groups_name, test_records.table_groups_name)
)
INSERT INTO score_definition_results_breakdown
SELECT id, definition_id, category, score_type, table_groups_id, table_name, column_name, dq_dimension, semantic_data_type, impact, score, issue_ct
FROM (
    SELECT
        gen_random_uuid() AS id,
        score_definitions.id AS definition_id,
        'semantic_data_type' AS category,
        'score' AS score_type,
        NULL AS table_groups_id,
        NULL AS table_name,
        NULL AS column_name,
        NULL AS dq_dimension,
        COALESCE(profiling_records.semantic_data_type, test_records.semantic_data_type) AS semantic_data_type,
        100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) AS impact,
        (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
        (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct,
        row_number() OVER (PARTITION BY score_definitions.id ORDER BY 100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) DESC)
    FROM profiling_records
    FULL OUTER JOIN test_records
        ON (
            test_records.project_code = profiling_records.project_code
            AND test_records.semantic_data_type = profiling_records.semantic_data_type
            AND test_records.table_groups_name = profiling_records.table_groups_name
        )
    INNER JOIN parent
        ON (
            (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
            AND (parent.table_groups_name = profiling_records.table_groups_name OR parent.table_groups_name = test_records.table_groups_name)
        )
    INNER JOIN score_definitions
        ON (
            (score_definitions.project_code = profiling_records.project_code OR score_definitions.project_code = test_records.project_code)
            AND (score_definitions.name = profiling_records.table_groups_name OR score_definitions.name = test_records.table_groups_name)
        )
) AS results
WHERE row_number <= 100;

-- Results Breakdown by "table_name" for "cde_score"
WITH
profiling_records AS (
    SELECT
        project_code,
        table_groups_id,
        table_groups_name,
        table_name,
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE NULLIF(table_name, '') IS NOT NULL
        AND critical_data_element = true
    GROUP BY project_code, table_groups_id, table_groups_name, table_name
),
test_records AS (
    SELECT
        project_code,
        table_groups_id,
        table_groups_name,
        table_name,
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_column
    WHERE NULLIF(table_name, '') IS NOT NULL
        AND critical_data_element = true
    GROUP BY project_code, table_groups_id, table_groups_name, table_name
),
parent AS (
    SELECT
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        COALESCE(profiling_records.table_groups_name, test_records.table_groups_name) AS table_groups_name,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code), COALESCE(profiling_records.table_groups_name, test_records.table_groups_name)
)
INSERT INTO score_definition_results_breakdown
SELECT id, definition_id, category, score_type, table_groups_id, table_name, column_name, dq_dimension, semantic_data_type, impact, score, issue_ct
FROM (
    SELECT
        gen_random_uuid() AS id,
        score_definitions.id AS definition_id,
        'table_name' AS category,
        'score' AS score_type,
        COALESCE(profiling_records.table_groups_id, test_records.table_groups_id) AS table_groups_id,
        COALESCE(profiling_records.table_name, test_records.table_name) AS table_name,
        NULL AS column_name,
        NULL AS dq_dimension,
        NULL AS semantic_data_type,
        100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) AS impact,
        (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
        (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct,
        row_number() OVER (PARTITION BY score_definitions.id ORDER BY 100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) DESC)
    FROM profiling_records
    FULL OUTER JOIN test_records
        ON (test_records.project_code = profiling_records.project_code AND test_records.table_groups_id = profiling_records.table_groups_id AND test_records.table_name = profiling_records.table_name)
    INNER JOIN parent
        ON (
            (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
            AND (parent.table_groups_name = profiling_records.table_groups_name OR parent.table_groups_name = test_records.table_groups_name)
        )
    INNER JOIN score_definitions
        ON (
            (score_definitions.project_code = profiling_records.project_code OR score_definitions.project_code = test_records.project_code)
            AND (score_definitions.name = profiling_records.table_groups_name OR score_definitions.name = test_records.table_groups_name)
        )
) AS results
WHERE row_number <= 100;

-- Results Breakdown by "column_name" for "cde_score"
WITH
profiling_records AS (
    SELECT
        project_code,
        table_groups_id,
        table_groups_name,
        table_name,
        column_name,
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE NULLIF(column_name, '') IS NOT NULL
        AND critical_data_element = true
    GROUP BY project_code, table_groups_id, table_groups_name, table_name, column_name
),
test_records AS (
    SELECT
        project_code,
        table_groups_id,
        table_groups_name,
        table_name,
        column_name,
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_column
    WHERE NULLIF(column_name, '') IS NOT NULL
        AND critical_data_element = true
    GROUP BY project_code, table_groups_id, table_groups_name, table_name, column_name
),
parent AS (
    SELECT
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        COALESCE(profiling_records.table_groups_name, test_records.table_groups_name) AS table_groups_name,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code), COALESCE(profiling_records.table_groups_name, test_records.table_groups_name)
)
INSERT INTO score_definition_results_breakdown
SELECT id, definition_id, category, score_type, table_groups_id, table_name, column_name, dq_dimension, semantic_data_type, impact, score, issue_ct
FROM (
    SELECT
        gen_random_uuid() AS id,
        score_definitions.id AS definition_id,
        'column_name' AS category,
        'cde_score' AS score_type,
        COALESCE(profiling_records.table_groups_id, test_records.table_groups_id) AS table_groups_id,
        COALESCE(profiling_records.table_name, test_records.table_name) AS table_name,
        COALESCE(profiling_records.column_name, test_records.column_name) AS column_name,
        NULL AS dq_dimension,
        NULL AS semantic_data_type,
        100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) AS impact,
        (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
        (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct,
        row_number() OVER (PARTITION BY score_definitions.id ORDER BY 100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) DESC)
    FROM profiling_records
    FULL OUTER JOIN test_records
        ON (test_records.project_code = profiling_records.project_code AND test_records.table_groups_id = profiling_records.table_groups_id AND test_records.table_name = profiling_records.table_name AND test_records.column_name = profiling_records.column_name)
    INNER JOIN parent
        ON (
            (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
            AND (parent.table_groups_name = profiling_records.table_groups_name OR parent.table_groups_name = test_records.table_groups_name)
        )
    INNER JOIN score_definitions
        ON (
            (score_definitions.project_code = profiling_records.project_code OR score_definitions.project_code = test_records.project_code)
            AND (score_definitions.name = profiling_records.table_groups_name OR score_definitions.name = test_records.table_groups_name)
        )
) AS results
WHERE row_number <= 100;

-- Results Breakdown by "dq_dimension" for "cde_score"
WITH
profiling_records AS (
    SELECT
        project_code,
        table_groups_name,
        dq_dimension,
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_dimension
    WHERE NULLIF(dq_dimension, '') IS NOT NULL
        AND critical_data_element = true
    GROUP BY project_code, table_groups_name, dq_dimension
),
test_records AS (
    SELECT
        project_code,
        table_groups_name,
        dq_dimension,
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_dimension
    WHERE NULLIF(dq_dimension, '') IS NOT NULL
        AND critical_data_element = true
    GROUP BY project_code, table_groups_name, dq_dimension
),
parent AS (
    SELECT
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        COALESCE(profiling_records.table_groups_name, test_records.table_groups_name) AS table_groups_name,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code), COALESCE(profiling_records.table_groups_name, test_records.table_groups_name)
)
INSERT INTO score_definition_results_breakdown
SELECT id, definition_id, category, score_type, table_groups_id, table_name, column_name, dq_dimension, semantic_data_type, impact, score, issue_ct
FROM (
    SELECT
        gen_random_uuid() AS id,
        score_definitions.id AS definition_id,
        'dq_dimension' AS category,
        'cde_score' AS score_type,
        NULL AS table_groups_id,
        NULL AS table_name,
        NULL AS column_name,
        COALESCE(profiling_records.dq_dimension, test_records.dq_dimension) AS dq_dimension,
        NULL AS semantic_data_type,
        100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) AS impact,
        (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
        (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct,
        row_number() OVER (PARTITION BY score_definitions.id ORDER BY 100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) DESC)
    FROM profiling_records
    FULL OUTER JOIN test_records
        ON (
            test_records.project_code = profiling_records.project_code
            AND test_records.dq_dimension = profiling_records.dq_dimension
            AND test_records.table_groups_name = profiling_records.table_groups_name
        )
    INNER JOIN parent
        ON (
            (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
            AND (parent.table_groups_name = profiling_records.table_groups_name OR parent.table_groups_name = test_records.table_groups_name)
        )
    INNER JOIN score_definitions
        ON (
            (score_definitions.project_code = profiling_records.project_code OR score_definitions.project_code = test_records.project_code)
            AND (score_definitions.name = profiling_records.table_groups_name OR score_definitions.name = test_records.table_groups_name)
        )
) AS results
WHERE row_number <= 100;

-- Results Breakdown by "semantic_data_type" for "cde_score"
WITH
profiling_records AS (
    SELECT
        project_code,
        table_groups_name,
        semantic_data_type,
        SUM(issue_ct) AS issue_ct,
        SUM(record_ct) AS data_point_ct,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE NULLIF(semantic_data_type, '') IS NOT NULL
        AND critical_data_element = true
    GROUP BY project_code, table_groups_name, semantic_data_type
),
test_records AS (
    SELECT
        project_code,
        table_groups_name,
        semantic_data_type,
        SUM(issue_ct) AS issue_ct,
        SUM(dq_record_ct) AS data_point_ct,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score
    FROM v_dq_test_scoring_latest_by_column
    WHERE NULLIF(semantic_data_type, '') IS NOT NULL
        AND critical_data_element = true
    GROUP BY project_code, table_groups_name, semantic_data_type
),
parent AS (
    SELECT
        COALESCE(profiling_records.project_code, test_records.project_code) AS project_code,
        COALESCE(profiling_records.table_groups_name, test_records.table_groups_name) AS table_groups_name,
        SUM(COALESCE(profiling_records.record_ct, 0)) AS profiling_data_points,
        SUM(COALESCE(test_records.dq_record_ct, 0)) AS test_data_points
    FROM v_dq_profile_scoring_latest_by_column AS profiling_records
    FULL OUTER JOIN v_dq_test_scoring_latest_by_column AS test_records ON (
        test_records.project_code = profiling_records.project_code
        AND test_records.table_groups_id = profiling_records.table_groups_id
        AND test_records.table_name = profiling_records.table_name
        AND test_records.column_name = profiling_records.column_name
    )
    GROUP BY COALESCE(profiling_records.project_code, test_records.project_code), COALESCE(profiling_records.table_groups_name, test_records.table_groups_name)
)
INSERT INTO score_definition_results_breakdown
SELECT id, definition_id, category, score_type, table_groups_id, table_name, column_name, dq_dimension, semantic_data_type, impact, score, issue_ct
FROM (
    SELECT
        gen_random_uuid() AS id,
        score_definitions.id AS definition_id,
        'semantic_data_type' AS category,
        'cde_score' AS score_type,
        NULL AS table_groups_id,
        NULL AS table_name,
        NULL AS column_name,
        NULL AS dq_dimension,
        COALESCE(profiling_records.semantic_data_type, test_records.semantic_data_type) AS semantic_data_type,
        100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) AS impact,
        (COALESCE(profiling_records.score, 1) * COALESCE(test_records.score, 1)) AS score,
        (COALESCE(profiling_records.issue_ct, 0) + COALESCE(test_records.issue_ct, 0)) AS issue_ct,
        row_number() OVER (PARTITION BY score_definitions.id ORDER BY 100 * (
            COALESCE(profiling_records.data_point_ct * (1 - profiling_records.score) / NULLIF(parent.profiling_data_points, 0), 0)
            + COALESCE(test_records.data_point_ct * (1 - test_records.score) / NULLIF(parent.test_data_points, 0), 0)
        ) DESC)
    FROM profiling_records
    FULL OUTER JOIN test_records
        ON (
            test_records.project_code = profiling_records.project_code
            AND test_records.semantic_data_type = profiling_records.semantic_data_type
            AND test_records.table_groups_name = profiling_records.table_groups_name
        )
    INNER JOIN parent
        ON (
            (parent.project_code = profiling_records.project_code OR parent.project_code = test_records.project_code)
            AND (parent.table_groups_name = profiling_records.table_groups_name OR parent.table_groups_name = test_records.table_groups_name)
        )
    INNER JOIN score_definitions
        ON (
            (score_definitions.project_code = profiling_records.project_code OR score_definitions.project_code = test_records.project_code)
            AND (score_definitions.name = profiling_records.table_groups_name OR score_definitions.name = test_records.table_groups_name)
        )
) AS results
WHERE row_number <= 100;
