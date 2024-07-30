SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_results
  ADD COLUMN test_suite_id UUID;

UPDATE test_results
   SET test_suite_id = s.id
  FROM test_results r
INNER JOIN test_suites s
   ON (r.table_groups_id = s.table_groups_id
  AND  r.test_suite = s.test_suite)
 WHERE test_results.id = r.id;

CREATE INDEX ix_tr_ts_tctt
   ON test_results(test_suite_id, table_name, column_names, test_type);

ALTER TABLE test_definitions
  ADD COLUMN test_suite_id UUID;

UPDATE test_definitions
   SET test_suite_id = s.id
  FROM test_definitions d
INNER JOIN test_suites s
   ON (D.table_groups_id = s.table_groups_id
  AND  d.test_suite = s.test_suite)
 WHERE test_definitions.id = d.id;

CREATE INDEX ix_td_ts_tc
   ON test_definitions(test_suite_id, table_name, column_name, test_type);

ALTER TABLE table_groups
   ADD COLUMN data_source            VARCHAR(40),
   ADD COLUMN source_system          VARCHAR(40),
   ADD COLUMN data_location          VARCHAR(40),
   ADD COLUMN source_process         VARCHAR(40),
   ADD COLUMN business_domain        VARCHAR(40),
   ADD COLUMN stakeholder_group      VARCHAR(40),
   ADD COLUMN transform_level        VARCHAR(40);

ALTER TABLE data_table_chars
   RENAME COLUMN transformation_level to transform_level;

ALTER TABLE data_column_chars
   RENAME COLUMN transformation_level to transform_level;
