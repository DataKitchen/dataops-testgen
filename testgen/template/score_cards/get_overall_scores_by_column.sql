SELECT
    (COALESCE(profiling_scores.score, 1) * COALESCE(test_scores.score, 1)) AS score,
    (COALESCE(profiling_scores.cde_score, 1) * COALESCE(test_scores.cde_score, 1)) AS cde_score,
    profiling_scores.score AS profiling_score,
    test_scores.score AS testing_score
FROM (
    SELECT
        project_code,
        SUM(good_data_pct * record_ct) / NULLIF(SUM(record_ct), 0) AS score,
        SUM(CASE critical_data_element WHEN true THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE critical_data_element WHEN true THEN record_ct ELSE 0 END), 0) AS cde_score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE {filters}
    GROUP BY project_code
)  AS profiling_scores
FULL OUTER JOIN (
    SELECT
        project_code,
        SUM(good_data_pct * dq_record_ct) / NULLIF(SUM(dq_record_ct), 0) AS score,
            SUM(CASE critical_data_element WHEN true THEN (good_data_pct * dq_record_ct) ELSE 0 END)
                / NULLIF(SUM(CASE critical_data_element WHEN true THEN dq_record_ct ELSE 0 END), 0) AS cde_score
    FROM v_dq_test_scoring_latest_by_column
    WHERE {filters}
    GROUP BY project_code
) AS test_scores
    ON (test_scores.project_code = profiling_scores.project_code)