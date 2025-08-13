SELECT DISTINCT ON (last_run_time)
    COALESCE(profiling_scores.project_code, test_scores.project_code) AS project_code,
    COALESCE(profiling_scores.definition_id, test_scores.definition_id) AS definition_id,
    COALESCE(profiling_scores.last_run_time, test_scores.last_run_time) AS last_run_time,
    (COALESCE(profiling_scores.score, 1) * COALESCE(test_scores.score, 1)) AS score,
    (COALESCE(profiling_scores.cde_score, 1) * COALESCE(test_scores.cde_score, 1)) AS cde_score
FROM (
    SELECT
        project_code,
        history.definition_id,
        history.last_run_time,
        SUM(good_data_pct * record_ct) / NULLIF(SUM(record_ct), 0) AS score,
        SUM(CASE critical_data_element WHEN true THEN (good_data_pct * record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE critical_data_element WHEN true THEN record_ct ELSE 0 END), 0) AS cde_score
    FROM v_dq_profile_scoring_history_by_column
    INNER JOIN score_definition_results_history AS history
        ON (
            history.definition_id = v_dq_profile_scoring_history_by_column.definition_id
            AND history.last_run_time = v_dq_profile_scoring_history_by_column.score_history_cutoff_time
        )
    WHERE {filters}
        AND history.definition_id = :definition_id
    GROUP BY project_code,
        history.definition_id,
        history.last_run_time
)  AS profiling_scores
FULL OUTER JOIN (
    SELECT
        project_code,
        history.definition_id,
        history.last_run_time,
        SUM(good_data_pct * dq_record_ct) / NULLIF(SUM(dq_record_ct), 0) AS score,
        SUM(CASE critical_data_element WHEN true THEN (good_data_pct * dq_record_ct) ELSE 0 END)
            / NULLIF(SUM(CASE critical_data_element WHEN true THEN dq_record_ct ELSE 0 END), 0) AS cde_score
    FROM v_dq_test_scoring_history_by_column
    INNER JOIN score_definition_results_history AS history
        ON (
            history.definition_id = v_dq_test_scoring_history_by_column.definition_id
            AND history.last_run_time = v_dq_test_scoring_history_by_column.score_history_cutoff_time
        )
    WHERE {filters}
        AND history.definition_id = :definition_id
    GROUP BY project_code,
        history.definition_id,
        history.last_run_time
) AS test_scores
	ON (
    test_scores.project_code = profiling_scores.project_code
    AND test_scores.definition_id = profiling_scores.definition_id
    AND test_scores.last_run_time = profiling_scores.last_run_time
  )
