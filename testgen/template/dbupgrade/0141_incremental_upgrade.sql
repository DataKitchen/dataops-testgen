SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE profile_results
   ADD COLUMN non_printing_ct BIGINT;

ALTER TABLE test_definitions
   ALTER COLUMN groupby_names TYPE VARCHAR,
   ALTER COLUMN match_groupby_names TYPE VARCHAR;

DROP VIEW IF EXISTS v_test_results;
DROP VIEW IF EXISTS v_queued_observability_results;

ALTER TABLE test_results
   ALTER COLUMN input_parameters TYPE VARCHAR;

UPDATE profile_anomaly_results
   SET detail = REPLACE(detail, 'Filled Values:', 'Dummy Values:')
 WHERE detail ILIKE 'Filled Values:%'
