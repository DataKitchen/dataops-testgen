-- Each table's key: the first-ranked column with a distinct value in every row and a value hash,
-- which excludes booleans. Binary floats and text longer than 100 characters are excluded. The key's
-- canonical text rounds a number to six places and truncates a time to the second, so values distinct
-- only below that would share it: date and time columns other than DATE are excluded, and so are
-- numbers declared with more than six decimal places, or declared with no scale and holding fractions.
WITH candidates AS (
  SELECT *,
         LOWER(TRIM(SPLIT_PART(COALESCE(NULLIF(db_data_type, ''), column_type), '(', 1))) AS base_type,
         CAST(COALESCE(SUBSTRING(db_data_type FROM ',\s*(\d+)\s*\)'),
                       SUBSTRING(column_type FROM ',\s*(\d+)\s*\)')) AS INTEGER) AS declared_scale
    FROM profile_results
   WHERE profile_run_id = :PROFILE_RUN_ID ::UUID
),
ranked_candidates AS (
  SELECT table_name,
         column_name,
         ROW_NUMBER() OVER (
           PARTITION BY table_name
           -- A surrogate key ranks after a natural one: a reload that regenerates it fails every keyed test
           ORDER BY CASE
                      WHEN functional_data_type LIKE 'ID%SK' THEN 1
                      WHEN functional_data_type LIKE 'ID%' THEN 0
                      ELSE 2
                    END,
                    CASE
                      WHEN general_type = 'N' AND COALESCE(fractional_sum, 0) = 0 THEN 0
                      WHEN general_type = 'D' THEN 1
                      WHEN general_type = 'A' THEN 2
                      ELSE 3
                    END,
                    avg_length,
                    position,
                    column_name
         ) AS candidate_rank
    FROM candidates
   WHERE record_ct > 0
     AND value_ct = record_ct
     AND null_value_ct = 0
     AND distinct_value_ct = value_ct
     AND multiset_hash IS NOT NULL
     AND base_type <> ALL(:FLOAT_TYPES)
     AND (general_type <> 'A' OR max_length <= 100)
     AND (general_type <> 'D' OR base_type = 'date')
     AND (general_type <> 'N'
          OR CASE WHEN declared_scale IS NULL THEN COALESCE(fractional_sum, 0) = 0 ELSE declared_scale <= 6 END)
)
UPDATE profile_results p
   SET key_column_name = c.column_name
  FROM ranked_candidates c
 WHERE p.profile_run_id = :PROFILE_RUN_ID ::UUID
   AND p.table_name = c.table_name
   AND c.candidate_rank = 1;
