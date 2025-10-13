SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE target_data_lookups
  ADD CONSTRAINT target_data_lookups_test_id_sql_flavor_error_type_pk
    PRIMARY KEY (test_id, sql_flavor, error_type);
