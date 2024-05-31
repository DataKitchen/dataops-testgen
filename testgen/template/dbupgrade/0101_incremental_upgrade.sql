SET SEARCH_PATH TO {SCHEMA_NAME};

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        where table_schema = '{SCHEMA_NAME}'
        and table_name='projects'
        AND column_name='observability_api_url'
    ) THEN
		alter table {SCHEMA_NAME}.projects add column observability_api_url TEXT DEFAULT '';
        update {SCHEMA_NAME}.projects set observability_api_url='{OBSERVABILITY_URL}' WHERE observability_api_url = '';
    END IF;
END $$;
