SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_templates DROP COLUMN template_name;

ALTER TABLE test_templates ADD COLUMN template VARCHAR;
