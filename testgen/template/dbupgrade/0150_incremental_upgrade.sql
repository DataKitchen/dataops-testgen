SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_suites
  ADD COLUMN view_mode VARCHAR(20) DEFAULT NULL;

ALTER TABLE table_groups
  ADD COLUMN monitor_test_suite_id UUID DEFAULT NULL;

ALTER TABLE table_groups ADD CONSTRAINT table_groups_test_suites_monitor_test_suite_id_fk
    FOREIGN KEY (monitor_test_suite_id) REFERENCES test_suites ON DELETE SET NULL;
