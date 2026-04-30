SELECT
    COALESCE(profiling_category_scores.category, test_category_scores.category) AS label,
    (COALESCE(profiling_category_scores.score, 1) * COALESCE(test_category_scores.score, 1)) AS score
FROM (
    SELECT
        {category} AS category,
        SUM(COALESCE(good_data_pct * weighted_record_ct, 0)) / NULLIF(SUM(COALESCE(weighted_record_ct, 0)), 0) AS score
    FROM v_dq_profile_scoring_latest_by_column
    WHERE NULLIF({category}, '') IS NOT NULL AND {filters}
    GROUP BY {category}
)  AS profiling_category_scores
FULL OUTER JOIN (
    SELECT
        {category} AS category,
        SUM(COALESCE(good_data_pct * weighted_dq_record_ct, 0)) / NULLIF(SUM(COALESCE(weighted_dq_record_ct, 0)), 0) AS score
    FROM v_dq_test_scoring_latest_by_column
    WHERE NULLIF({category}, '') IS NOT NULL AND {filters}
    GROUP BY {category}
) AS test_category_scores
    ON (test_category_scores.category = profiling_category_scores.category)
