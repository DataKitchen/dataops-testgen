SET SEARCH_PATH TO {SCHEMA_NAME};

alter table {SCHEMA_NAME}.profiling_runs add column process_id INTEGER;
alter table {SCHEMA_NAME}.test_runs add column process_id INTEGER;
