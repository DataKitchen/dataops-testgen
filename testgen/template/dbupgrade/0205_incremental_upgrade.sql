SET SEARCH_PATH TO {SCHEMA_NAME};

-- stg_functional_table_updates carries neither a table group nor a run id, and nothing deletes
-- its rows per run, so the run that staged a row is only identifiable by profile_run_id.
ALTER TABLE stg_functional_table_updates ADD COLUMN profile_run_id UUID;
