SET SEARCH_PATH TO {SCHEMA_NAME};

-- How a row's percentiles were computed: 'exact' or 'approximate'. NULL on rows that carry no
-- percentiles (non-numeric columns, error rows) and on rows written before the column existed.
ALTER TABLE profile_results
    ADD COLUMN IF NOT EXISTS percentile_method VARCHAR(20);
