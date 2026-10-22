SET SEARCH_PATH TO {SCHEMA_NAME};

-- PostgreSQL refuses to alter a column a view depends on. Views are rebuilt from 060 on every upgrade.
DROP VIEW IF EXISTS v_queued_observability_results CASCADE;

ALTER TABLE table_groups
    ALTER COLUMN profiling_table_set TYPE TEXT,
    ALTER COLUMN profiling_include_mask TYPE TEXT,
    ALTER COLUMN profiling_exclude_mask TYPE TEXT;
