SET SEARCH_PATH TO {SCHEMA_NAME};

-- Key each staging table to the run that staged it, rather than to the run date.
--
-- A run stages its rows, reads them back to reconcile against the durable table, then deletes
-- them. Keying that round trip on a timestamp truncated to whole seconds means two runs over the
-- same table group or test suite that start within one second share a key: each reads the other's
-- rows and each deletes them. For the data characteristics refresh the reconciliation reads an
-- empty scan as "every table and column disappeared" and drops the table group's whole catalog.
--
-- Columns are nullable so rows staged by a run in flight during this upgrade stop matching any
-- key instead of being reconciled under the wrong one. They are aged out by data retention.

ALTER TABLE stg_data_chars_updates
    ADD COLUMN IF NOT EXISTS refresh_id UUID;

ALTER TABLE stg_test_definition_updates
    ADD COLUMN IF NOT EXISTS test_run_id UUID;

CREATE INDEX IF NOT EXISTS ix_sdcu_refresh
    ON stg_data_chars_updates(refresh_id);

CREATE INDEX IF NOT EXISTS ix_stdu_test_run
    ON stg_test_definition_updates(test_run_id);

-- stg_functional_table_updates is read by profile_run_id and deleted by it, so index the column
-- both use.
CREATE INDEX IF NOT EXISTS ix_sftu_profile_run
    ON stg_functional_table_updates(profile_run_id);

-- Rows left by runs that predate the per-run delete. Data retention can be disabled per project,
-- so these are cleared here rather than left to age out.
DELETE FROM stg_functional_table_updates;
