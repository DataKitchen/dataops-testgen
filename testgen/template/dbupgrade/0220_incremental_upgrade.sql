SET SEARCH_PATH TO {SCHEMA_NAME};

-- v_queued_observability_results selects profile_sample_percent, and PostgreSQL refuses to
-- alter a column a view depends on. Views are rebuilt from 060 on every upgrade.
DROP VIEW IF EXISTS v_queued_observability_results;

-- Neither column has ever had a meaning outside a plain non-negative integer, so anything
-- else is unparseable data. It takes the column default rather than failing the upgrade.
--
-- The ::text casts keep this re-runnable. The runner commits a script and bumps tg_revision
-- in separate calls, so a process that dies between them re-applies the script against
-- columns that are already INTEGER, and TRIM() has no integer overload.
ALTER TABLE table_groups
    ALTER COLUMN profile_sample_percent DROP DEFAULT,
    ALTER COLUMN profile_sample_percent TYPE INTEGER
        USING CASE
            WHEN profile_sample_percent IS NULL THEN NULL
            WHEN TRIM(profile_sample_percent::text) ~ '^\d+$' THEN TRIM(profile_sample_percent::text)::INTEGER
            ELSE 30
        END,
    ALTER COLUMN profile_sample_percent SET DEFAULT 30;

ALTER TABLE table_groups
    ALTER COLUMN profiling_delay_days DROP DEFAULT,
    ALTER COLUMN profiling_delay_days TYPE INTEGER
        USING CASE
            WHEN profiling_delay_days IS NULL THEN NULL
            WHEN TRIM(profiling_delay_days::text) ~ '^\d+$' THEN TRIM(profiling_delay_days::text)::INTEGER
            ELSE 0
        END,
    ALTER COLUMN profiling_delay_days SET DEFAULT 0;
