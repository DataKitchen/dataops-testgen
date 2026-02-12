WITH latest_run AS (
  -- Latest complete profiling run before as-of-date
  SELECT MAX(run_date) AS last_run_date
    FROM profile_results
  WHERE table_groups_id = :TABLE_GROUPS_ID ::UUID
    AND run_date::DATE <= :AS_OF_DATE ::DATE
),
latest_results AS (
  -- Column results for latest run
  SELECT p.profile_run_id, p.schema_name, p.table_name, p.column_name,
    p.functional_data_type, p.general_type,
    p.distinct_value_ct, p.record_ct, p.null_value_ct,
    p.max_value, p.min_value, p.avg_value, p.stdev_value
  FROM profile_results p
    INNER JOIN latest_run lr ON p.run_date = lr.last_run_date
    INNER JOIN data_table_chars dtc ON (
      dtc.table_groups_id = p.table_groups_id
      AND dtc.schema_name = p.schema_name
      AND dtc.table_name = p.table_name
      -- Ignore dropped tables
      AND dtc.drop_date IS NULL
    )
  WHERE p.table_groups_id = :TABLE_GROUPS_ID ::UUID
),
-- IDs - TOP 2
id_cols AS (
  SELECT profile_run_id, schema_name, table_name, column_name,
    functional_data_type, general_type, distinct_value_ct,
    ROW_NUMBER() OVER (
      PARTITION BY schema_name, table_name
      ORDER BY
        CASE
          WHEN functional_data_type ILIKE 'ID-Unique%' THEN 1
          WHEN functional_data_type = 'ID-Secondary' THEN 2
          ELSE 3
        END, distinct_value_ct DESC, column_name
    ) AS rank
  FROM latest_results
  WHERE general_type IN ('A', 'D', 'N')
    AND functional_data_type ILIKE 'ID%'
),
-- Process Date - TOP 1
process_date_cols AS (
  SELECT profile_run_id, schema_name, table_name, column_name,
    functional_data_type, general_type, distinct_value_ct,
    ROW_NUMBER() OVER (
      PARTITION BY schema_name, table_name
      ORDER BY
        CASE
          WHEN column_name ILIKE '%mod%' THEN 1
          WHEN column_name ILIKE '%up%'  THEN 1
          WHEN column_name ILIKE '%cr%'  THEN 2
          WHEN column_name ILIKE '%in%'  THEN 2
        END, distinct_value_ct DESC, column_name
    ) AS rank
  FROM latest_results
  WHERE general_type IN ('A', 'D', 'N')
    AND functional_data_type ILIKE 'process%'
),
-- Transaction Date - TOP 1
tran_date_cols AS (
  SELECT profile_run_id, schema_name, table_name, column_name,
    functional_data_type, general_type, distinct_value_ct,
    ROW_NUMBER() OVER (
      PARTITION BY schema_name, table_name
      ORDER BY distinct_value_ct DESC, column_name
    ) AS rank
  FROM latest_results
  WHERE general_type IN ('A', 'D', 'N')
    AND functional_data_type ILIKE 'transactional date%'
    OR functional_data_type ILIKE 'period%'
    OR functional_data_type = 'timestamp'
),
-- Numeric Measures
numeric_cols AS (
  SELECT profile_run_id, schema_name, table_name, column_name,
    functional_data_type, general_type,
/*
  -- Subscores
  distinct_value_ct * 1.0 / NULLIF(record_ct, 0)                              AS cardinality_score,
  (max_value - min_value) / NULLIF(ABS(NULLIF(avg_value, 0)), 1)              AS range_score,
  LEAST(1, LOG(GREATEST(distinct_value_ct, 2))) / LOG(GREATEST(record_ct, 2)) AS nontriviality_score,
  stdev_value / NULLIF(ABS(NULLIF(avg_value, 0)), 1)                          AS variability_score,
  1.0 - (null_value_ct * 1.0 / NULLIF(NULLIF(record_ct, 0), 1))               AS null_penalty,
*/
  -- Weighted score
  (
    0.25 * (distinct_value_ct * 1.0 / NULLIF(record_ct, 0)) +
    0.15 * ((max_value - min_value) / NULLIF(ABS(NULLIF(avg_value, 0)), 1)) +
    0.10 * (LEAST(1, LOG(GREATEST(distinct_value_ct, 2))) / LOG(GREATEST(record_ct, 2))) +
    0.40 * (stdev_value / NULLIF(ABS(NULLIF(avg_value, 0)), 1)) +
    0.10 * (1.0 - (null_value_ct * 1.0 / NULLIF(NULLIF(record_ct, 0), 1)))
  ) AS change_detection_score
  FROM latest_results
  WHERE general_type = 'N'
    AND (
      functional_data_type ILIKE 'Measure%'
      OR functional_data_type IN ('Sequence', 'Constant')
    )
),
numeric_cols_ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY schema_name, table_name
      ORDER BY change_detection_score DESC, column_name
    ) AS rank
  FROM numeric_cols
  WHERE change_detection_score IS NOT NULL
),
combined AS (
  SELECT profile_run_id, schema_name, table_name, column_name,
    'ID' AS element_type, general_type, 10 + rank AS fingerprint_order
  FROM id_cols
  WHERE rank <= 2
  UNION ALL
  SELECT profile_run_id, schema_name, table_name, column_name,
    'DATE_P' AS element_type, general_type, 20 + rank AS fingerprint_order
  FROM process_date_cols
  WHERE rank = 1
  UNION ALL
  SELECT profile_run_id, schema_name, table_name, column_name,
    'DATE_T' AS element_type, general_type, 30 + rank AS fingerprint_order
  FROM tran_date_cols
  WHERE rank = 1
  UNION ALL
  SELECT profile_run_id, schema_name, table_name, column_name,
    'MEAS' AS element_type, general_type, 40 + rank AS fingerprint_order
  FROM numeric_cols_ranked
  WHERE rank = 1
),
selected_tables AS (
  SELECT profile_run_id, schema_name, table_name,
    STRING_AGG(column_name, ',' ORDER BY element_type, fingerprint_order, column_name) AS column_names,
    'CAST(COUNT(*) AS STRING) || "|" || ' ||
      STRING_AGG(
        REPLACE(
          CASE
            WHEN general_type = 'D' THEN 'CAST(MIN(@@@) AS STRING) || "|" || CAST(MAX(@@@) AS STRING) || "|" || CAST(COUNT(DISTINCT @@@) AS STRING)'
            WHEN general_type = 'A' THEN 'CAST(MIN(@@@) AS STRING) || "|" || CAST(MAX(@@@) AS STRING) || "|" || CAST(COUNT(DISTINCT @@@) AS STRING) || "|" || CAST(SUM(LENGTH(@@@)) AS STRING)'
            WHEN general_type = 'N' THEN 'ARRAY_TO_STRING([
              CAST(COUNT(@@@) AS STRING),
              CAST(COUNT(DISTINCT MOD(CAST(COALESCE(@@@,0) AS NUMERIC) * 1000000, CAST(1000003 AS NUMERIC))) AS STRING),
              COALESCE(CAST(ROUND(MIN(CAST(@@@ AS NUMERIC)), 6) AS STRING), ''''),
              COALESCE(CAST(ROUND(MAX(CAST(@@@ AS NUMERIC)), 6) AS STRING), ''''),
              CAST(MOD(COALESCE(SUM(MOD(CAST(ABS(COALESCE(@@@,0)) AS NUMERIC) * 1000000, CAST(1000000007 AS NUMERIC))), CAST(0 AS NUMERIC)), CAST(1000000007 AS NUMERIC)) AS STRING),
              CAST(MOD(COALESCE(SUM(MOD(CAST(ABS(COALESCE(@@@,0)) AS NUMERIC) * 1000000, CAST(1000000009 AS NUMERIC))), CAST(0 AS NUMERIC)), CAST(1000000009 AS NUMERIC)) AS STRING)
            ], ''|'', '''')'
          END,
          '@@@', '`' || column_name || '`'
        ),
        ' || "|" || '
        ORDER BY element_type, fingerprint_order, column_name
      ) AS fingerprint
  FROM combined
  GROUP BY profile_run_id, schema_name, table_name
)
-- Insert tests for selected tables
INSERT INTO test_definitions (
  table_groups_id, test_suite_id, test_type,
  schema_name, table_name, groupby_names,
  test_active, last_auto_gen_date, profiling_as_of_date, profile_run_id,
  history_calculation, history_lookback, custom_query
)
SELECT
  :TABLE_GROUPS_ID ::UUID AS table_groups_id,
  :TEST_SUITE_ID ::UUID   AS test_suite_id,
  'Freshness_Trend'       AS test_type,
  s.schema_name,
  s.table_name,
  s.column_names          AS groupby_names,
  'Y'                     AS test_active,
  :RUN_DATE ::TIMESTAMP   AS last_auto_gen_date,
  :AS_OF_DATE ::TIMESTAMP AS profiling_as_of_date,
  s.profile_run_id,
  'PREDICT'               AS history_calculation,
  NULL                    AS history_lookback,
  s.fingerprint           AS custom_query
FROM selected_tables s
  -- Only insert if test type is active
WHERE EXISTS (SELECT 1 FROM test_types WHERE test_type = 'Freshness_Trend' AND active = 'Y')
  -- Only insert if test type is included in generation set
  AND EXISTS (SELECT 1 FROM generation_sets WHERE test_type = 'Freshness_Trend' AND generation_set = :GENERATION_SET)
  {TABLE_FILTER}

-- Match "uix_td_autogen_table" unique index exactly
ON CONFLICT (test_suite_id, test_type, schema_name, table_name)
WHERE last_auto_gen_date IS NOT NULL
  AND table_name IS NOT NULL
  AND column_name IS NULL

-- Update tests if they already exist
DO UPDATE SET
  groupby_names        = EXCLUDED.groupby_names,
  test_active          = EXCLUDED.test_active,
  last_auto_gen_date   = EXCLUDED.last_auto_gen_date,
  profiling_as_of_date = EXCLUDED.profiling_as_of_date,
  profile_run_id       = EXCLUDED.profile_run_id,
  history_calculation  = EXCLUDED.history_calculation,
  history_lookback     = EXCLUDED.history_lookback,
  custom_query         = EXCLUDED.custom_query
-- Ignore locked tests
WHERE test_definitions.lock_refresh = 'N'
  -- Don't update existing tests in "insert" mode
  AND NOT COALESCE(:INSERT_ONLY, FALSE);
