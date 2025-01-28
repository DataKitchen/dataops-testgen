SET SEARCH_PATH TO {SCHEMA_NAME};

INSERT INTO score_definitions
SELECT
    gen_random_uuid() AS id,
    table_group.project_code AS project_code,
    table_group.table_groups_name AS name,
    true AS total_score,
    false AS cde_score,
    'dq_dimension' AS category
FROM table_groups AS table_group;

INSERT INTO score_definition_filters
SELECT
    gen_random_uuid() AS id,
    score_definition.id AS definition_id,
    'table_groups_name' AS field,
    table_group.table_groups_name AS value
FROM table_groups AS table_group
INNER JOIN score_definitions AS score_definition
    ON (score_definition.project_code = table_group.project_code AND score_definition.name = table_group.table_groups_name);

WITH
profiling_cols AS (
    SELECT
        table_groups_id,
        table_groups_name,
        SUM(record_ct * good_data_pct) / NULLIF(SUM(record_ct), 0) AS score,
        SUM(CASE critical_data_element WHEN true THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE critical_data_element WHEN true THEN record_ct ELSE 0 END), 0) AS cde_score
    FROM v_dq_profile_scoring_latest_by_column
    GROUP BY table_groups_id, table_groups_name
),
profiling_dims AS (
    SELECT
        table_groups_id,
        SUM(CASE dq_dimension WHEN 'Accuracy' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Accuracy' THEN record_ct ELSE 0 END), 0) AS accuracy_score,
        SUM(CASE dq_dimension WHEN 'Completeness' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Completeness' THEN record_ct ELSE 0 END), 0) AS completeness_score,
        SUM(CASE dq_dimension WHEN 'Consistency' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Consistency' THEN record_ct ELSE 0 END), 0) AS consistency_score,
        SUM(CASE dq_dimension WHEN 'Timeliness' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Timeliness' THEN record_ct ELSE 0 END), 0) AS timeliness_score,
        SUM(CASE dq_dimension WHEN 'Uniqueness' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Uniqueness' THEN record_ct ELSE 0 END), 0) AS uniqueness_score,
        SUM(CASE dq_dimension WHEN 'Validity' THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Validity' THEN record_ct ELSE 0 END), 0) AS validity_score
    FROM v_dq_profile_scoring_latest_by_dimension
    GROUP BY table_groups_id
),
test_cols AS (
    SELECT
        table_groups_id,
        table_groups_name,
        SUM(dq_record_ct * good_data_pct) / NULLIF(SUM(dq_record_ct), 0) AS score,
        SUM(CASE critical_data_element WHEN true THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE critical_data_element WHEN true THEN dq_record_ct ELSE 0 END), 0) AS cde_score
    FROM v_dq_test_scoring_latest_by_column
    GROUP BY table_groups_id, table_groups_name
),
test_dims AS (
    SELECT
        table_groups_id,
        SUM(CASE dq_dimension WHEN 'Accuracy' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Accuracy' THEN dq_record_ct ELSE 0 END), 0) AS accuracy_score,
        SUM(CASE dq_dimension WHEN 'Completeness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Completeness' THEN dq_record_ct ELSE 0 END), 0) AS completeness_score,
        SUM(CASE dq_dimension WHEN 'Consistency' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Consistency' THEN dq_record_ct ELSE 0 END), 0) AS consistency_score,
        SUM(CASE dq_dimension WHEN 'Timeliness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Timeliness' THEN dq_record_ct ELSE 0 END), 0) AS timeliness_score,
        SUM(CASE dq_dimension WHEN 'Uniqueness' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Uniqueness' THEN dq_record_ct ELSE 0 END), 0) AS uniqueness_score,
        SUM(CASE dq_dimension WHEN 'Validity' THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE dq_dimension WHEN 'Validity' THEN dq_record_ct ELSE 0 END), 0) AS validity_score
    FROM v_dq_test_scoring_latest_by_dimension
    GROUP BY table_groups_id
)
INSERT INTO score_definition_results
SELECT
    definition_id,
    UNNEST(array['score', 'cde_score', 'profiling_score', 'testing_score', 'Accuracy', 'Completeness', 'Consistency', 'Timeliness', 'Uniqueness', 'Validity']) AS category,
    UNNEST(array[score, cde_score, profiling_score, testing_score, accuracy_score, completeness_score, consistency_score, timeliness_score, uniqueness_score, validity_score]) AS score
FROM (
    SELECT
        score_definition.id AS definition_id,
        COALESCE(profiling_cols.table_groups_id, test_cols.table_groups_id) AS id,
        COALESCE(profiling_cols.table_groups_name, test_cols.table_groups_name) AS name,
        (COALESCE(profiling_cols.score, 1) * COALESCE(test_cols.score, 1)) AS score,
        profiling_cols.score AS profiling_score,
        test_cols.score AS testing_score,
        (COALESCE(profiling_cols.cde_score, 1) * COALESCE(test_cols.cde_score, 1)) AS cde_score,
        (COALESCE(profiling_dims.accuracy_score, 1) * COALESCE(test_dims.accuracy_score, 1)) AS accuracy_score,
        (COALESCE(profiling_dims.completeness_score, 1) * COALESCE(test_dims.completeness_score, 1)) AS completeness_score,
        (COALESCE(profiling_dims.consistency_score, 1) * COALESCE(test_dims.consistency_score, 1)) AS consistency_score,
        (COALESCE(profiling_dims.timeliness_score, 1) * COALESCE(test_dims.timeliness_score, 1)) AS timeliness_score,
        (COALESCE(profiling_dims.uniqueness_score, 1) * COALESCE(test_dims.uniqueness_score, 1)) AS uniqueness_score,
        (COALESCE(profiling_dims.validity_score, 1) * COALESCE(test_dims.validity_score, 1)) AS validity_score
    FROM profiling_cols
    INNER JOIN profiling_dims
        ON (profiling_dims.table_groups_id = profiling_cols.table_groups_id)
    FULL OUTER JOIN test_cols
        ON (test_cols.table_groups_id = profiling_cols.table_groups_id)
    FULL OUTER JOIN test_dims
        ON (test_dims.table_groups_id = test_cols.table_groups_id)
    INNER JOIN table_groups AS table_group
        ON (table_group.id = profiling_cols.table_groups_id OR table_group.id = test_cols.table_groups_id)
    INNER JOIN score_definitions AS score_definition
        ON (score_definition.project_code = table_group.project_code AND score_definition.name = table_group.table_groups_name)
);
