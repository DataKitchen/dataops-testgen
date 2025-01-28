SELECT
    COALESCE(profiling_category_scores.category, test_category_scores.category) AS label,
    (COALESCE(profiling_category_scores.score, 1) * COALESCE(test_category_scores.score, 1)) AS score
FROM (
    SELECT
        {category} AS category,
        SUM(COALESCE(good_data_pct * record_ct, 0)) / NULLIF(SUM(COALESCE(record_ct, 0)), 0) AS score
    FROM v_dq_profile_scoring_latest_by_dimension
    WHERE NULLIF({category}, '') IS NOT NULL AND {filters}
    GROUP BY {category}
)  AS profiling_category_scores
FULL OUTER JOIN (
    SELECT
        {category} AS category,
        SUM(COALESCE(good_data_pct * dq_record_ct, 0)) / NULLIF(SUM(COALESCE(dq_record_ct, 0)), 0) AS score
    FROM v_dq_test_scoring_latest_by_dimension
    WHERE NULLIF({category}, '') IS NOT NULL AND {filters}
    GROUP BY {category}
) AS test_category_scores
    ON (test_category_scores.category = profiling_category_scores.category)