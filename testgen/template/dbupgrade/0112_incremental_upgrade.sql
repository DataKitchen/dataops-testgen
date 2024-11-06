SET SEARCH_PATH TO {SCHEMA_NAME};

UPDATE profile_anomaly_types SET anomaly_criteria = '(p.filled_value_ct > 0 OR p.zero_length_ct > 0)' WHERE id = '1002';
