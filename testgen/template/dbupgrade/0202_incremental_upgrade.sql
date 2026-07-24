SET SEARCH_PATH TO {SCHEMA_NAME};

-- The bulk-COPY write path did not constrain (table_groups_id, table_name, column_name,
-- profile_run_id), so an install that never had the unique index below could hold duplicate
-- rows on that key. Collapse any such duplicates to a single row (keeping the newest by ctid)
-- before enforcing uniqueness, otherwise CREATE UNIQUE INDEX would abort the upgrade.
DELETE FROM profile_results a
    USING profile_results b
    WHERE a.ctid < b.ctid
      AND a.table_groups_id = b.table_groups_id
      AND a.table_name = b.table_name
      AND a.column_name = b.column_name
      AND a.profile_run_id = b.profile_run_id;

-- The named upsert on profile_results relies on this unique index as its ON CONFLICT target.
-- It ships in the fresh-install schema (030) but no prior migration backfilled it, so installs
-- created before that baseline lack it. Create it here (no-op where already present).
CREATE UNIQUE INDEX IF NOT EXISTS uix_pr_tg_t_c_prun
    ON profile_results(table_groups_id, table_name, column_name, profile_run_id);
