-- Update table weights from functional_table_type on data_table_chars.
-- Uses ILIKE so both cumulative-entity and window-entity match %entity.
UPDATE data_table_chars dtc
   SET dq_score_weight = COALESCE(w.default_weight, 1.0)
  FROM dq_score_weight_defaults w
 WHERE dtc.table_groups_id = :TABLE_GROUPS_ID
   AND w.weight_scope = 'table'
   AND dtc.functional_table_type ILIKE w.semantic_type;

-- Reset table weight to 1.0 for rows that no longer match any pattern.
UPDATE data_table_chars dtc
   SET dq_score_weight = 1.0
 WHERE dtc.table_groups_id = :TABLE_GROUPS_ID
   AND dtc.dq_score_weight != 1.0
   AND NOT EXISTS (
       SELECT 1 FROM dq_score_weight_defaults w
        WHERE w.weight_scope = 'table'
          AND dtc.functional_table_type ILIKE w.semantic_type
   );

-- Update column weights from functional_data_type on data_column_chars.
UPDATE data_column_chars dcc
   SET dq_score_weight = COALESCE(w.default_weight, 1.0)
  FROM dq_score_weight_defaults w
 WHERE dcc.table_groups_id = :TABLE_GROUPS_ID
   AND w.weight_scope = 'column'
   AND dcc.functional_data_type = w.semantic_type;

-- Reset column weight to 1.0 for rows with no matching functional_data_type.
UPDATE data_column_chars dcc
   SET dq_score_weight = 1.0
 WHERE dcc.table_groups_id = :TABLE_GROUPS_ID
   AND dcc.dq_score_weight != 1.0
   AND NOT EXISTS (
       SELECT 1 FROM dq_score_weight_defaults w
        WHERE w.weight_scope = 'column'
          AND dcc.functional_data_type = w.semantic_type
   );

-- Update PII weights from pii_flag on data_column_chars.
-- Keys on the first character: 'A'/'B'/'C' for auto-detected risk tiers, 'M' for user-set 'MANUAL'.
UPDATE data_column_chars dcc
   SET dq_score_pii_weight = COALESCE(w.default_weight, 1.0)
  FROM dq_score_weight_defaults w
 WHERE dcc.table_groups_id = :TABLE_GROUPS_ID
   AND dcc.pii_flag IS NOT NULL
   AND w.weight_scope = 'pii'
   AND w.semantic_type = LEFT(dcc.pii_flag, 1);

-- Reset PII weight to 1.0 where pii_flag is NULL or no longer matches.
UPDATE data_column_chars dcc
   SET dq_score_pii_weight = 1.0
 WHERE dcc.table_groups_id = :TABLE_GROUPS_ID
   AND dcc.dq_score_pii_weight != 1.0
   AND dcc.pii_flag IS NULL;
