SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE data_table_chars
ADD COLUMN last_profile_record_ct BIGINT;

UPDATE data_table_chars
  SET last_profile_record_ct = p.calc_record_ct
 FROM (SELECT table_groups_id, table_name,
              MAX(record_ct) as calc_record_ct
         FROM v_latest_profile_results
       GROUP BY table_groups_id, table_name) p
WHERE (data_table_chars.table_groups_id = p.table_groups_id
  AND  data_table_chars.table_name = p.table_name);
