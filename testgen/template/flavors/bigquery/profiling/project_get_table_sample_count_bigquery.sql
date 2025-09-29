WITH stats AS (
  SELECT
    COUNT(*) * 1.0 AS record_ct,
    ROUND(CAST({PROFILE_SAMPLE_PERCENT} AS FLOAT64) * COUNT(*) * 1.0 / 100.0) AS calc_sample_ct,
    CAST({PROFILE_SAMPLE_MIN_COUNT} AS FLOAT64) AS min_sample_ct,
    CAST(999000 AS FLOAT64) AS max_sample_ct
  FROM `{SAMPLING_TABLE}`
)
SELECT '{SAMPLING_TABLE}' AS schema_table,
       CASE
         WHEN record_ct <= min_sample_ct     THEN -1
         WHEN calc_sample_ct > max_sample_ct THEN max_sample_ct
         WHEN calc_sample_ct > min_sample_ct THEN calc_sample_ct
                                             ELSE {PROFILE_SAMPLE_MIN_COUNT}
       END AS sample_count,
       CASE
         WHEN record_ct <= min_sample_ct     THEN 1
         WHEN calc_sample_ct > max_sample_ct THEN record_ct / max_sample_ct
         WHEN calc_sample_ct > min_sample_ct THEN record_ct / calc_sample_ct
                                             ELSE record_ct / min_sample_ct
       END AS sample_ratio,
       ROUND(
         CASE
           WHEN record_ct <= min_sample_ct     THEN 100
           WHEN calc_sample_ct > max_sample_ct THEN 100.0 * max_sample_ct / record_ct
           WHEN calc_sample_ct > min_sample_ct THEN 100.0 * calc_sample_ct / record_ct
                                               ELSE 100.0 * min_sample_ct / record_ct
         END,
       4) AS sample_percent_calc
FROM stats;
