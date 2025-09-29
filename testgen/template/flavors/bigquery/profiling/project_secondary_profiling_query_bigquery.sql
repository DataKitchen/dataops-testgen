WITH counts AS (
  SELECT
    `{COL_NAME}` AS col_val,
    COUNT(*) AS ct
  FROM `{DATA_SCHEMA}.{DATA_TABLE}`
  WHERE `{COL_NAME}` > ' '
-- TG-IF do_sample_bool
    AND RAND() * 100 < {SAMPLE_PERCENT_CALC}
-- TG-ENDIF
  GROUP BY `{COL_NAME}`
),
ranked AS (
  SELECT
    col_val,
    ct,
    ROW_NUMBER() OVER (ORDER BY ct DESC, col_val ASC) AS rn
  FROM counts
),
top10 AS (
  -- top 10 formatted rows
  SELECT
    rn,
    CONCAT('| ', CAST(col_val AS STRING), ' | ', CAST(ct AS STRING)) AS val
  FROM ranked
  WHERE rn <= 10
  ORDER BY rn
),
others_agg AS (
  SELECT
    11 AS rn,
    CONCAT(
      '| Other Values (',
      CAST(COUNT(DISTINCT col_val) AS STRING),
      ') | ',
      CAST(SUM(ct) AS STRING)
    ) AS val,
    COUNT(*) AS other_row_count
  FROM ranked
  WHERE rn > 10
),
all_vals AS (
  SELECT * FROM top10
  UNION ALL
  SELECT rn, val FROM others_agg WHERE other_row_count > 0
)
SELECT
  '{PROJECT_CODE}' AS project_code,
  '{DATA_SCHEMA}'  AS schema_name,
  '{RUN_DATE}'     AS run_date,
  '{DATA_TABLE}'   AS table_name,
  '{COL_NAME}'     AS column_name,
  (SELECT STRING_AGG(val, '\n' ORDER BY rn) FROM all_vals) AS top_freq_values,
  (SELECT TO_HEX(MD5(STRING_AGG(CAST(col_val AS STRING), '|' ORDER BY col_val)))
     FROM counts
  ) AS distinct_value_hash;
