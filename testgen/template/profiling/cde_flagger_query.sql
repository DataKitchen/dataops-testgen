UPDATE data_column_chars
   SET critical_data_element = FALSE
 WHERE table_groups_id = :TABLE_GROUPS_ID;

WITH cde_selects
   AS ( SELECT table_groups_id, table_name, column_name
--                ,functional_data_type,
--                record_ct,
--                ROUND(100.0 * (value_ct - COALESCE(zero_length_ct, 0.0) - COALESCE(filled_value_ct, 0.0))::DEC(15, 3) /
--                      NULLIF(record_ct::DEC(15, 3), 0), 0) AS pct_records_populated
          FROM profile_results p
         WHERE p.profile_run_id = :PROFILE_RUN_ID
           AND ROUND(100.0 * (value_ct - COALESCE(zero_length_ct, 0.0) - COALESCE(filled_value_ct, 0.0))::DEC(15, 3) /
                     NULLIF(record_ct::DEC(15, 3), 0), 0) > 75
           AND ((p.functional_table_type ILIKE '%Entity'
            AND p.functional_data_type IN ('Entity Name', 'City', 'State', 'Zip', 'Code', 'Category'))
            OR (p.functional_table_type ILIKE '%Domain'
               AND p.functional_data_type IN ('Category', 'Code'))
            OR (p.functional_table_type ILIKE '%Summary'
               AND (p.functional_data_type = 'Category'
                  OR p.functional_data_type ILIKE 'Period%'
                  OR p.functional_data_type ILIKE 'Measurement%'))
            OR (p.functional_table_type ILIKE '%transaction'
               AND (p.functional_data_type = 'Category'
                  OR p.functional_data_type ILIKE 'Transactional Date%'
                  OR p.functional_data_type ILIKE 'Measurement%')))
         )
UPDATE data_column_chars
   SET critical_data_element = TRUE
  FROM cde_selects
 WHERE data_column_chars.table_groups_id = cde_selects.table_groups_id
   AND data_column_chars.table_name = cde_selects.table_name
   AND data_column_chars.column_name = cde_selects.column_name;
