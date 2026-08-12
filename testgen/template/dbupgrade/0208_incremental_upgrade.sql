SET SEARCH_PATH TO {SCHEMA_NAME};

-- Remove the disabled pairwise-contingency feature
DROP TABLE IF EXISTS profile_pair_rules;

ALTER TABLE table_groups
    DROP COLUMN IF EXISTS profile_do_pair_rules,
    DROP COLUMN IF EXISTS profile_pair_rule_pct;

-- Remove the unused functional_test_results table
DROP TABLE IF EXISTS functional_test_results;

-- Remove unused functions
DROP FUNCTION IF EXISTS {SCHEMA_NAME}.fn_pct(NUMERIC, NUMERIC, INTEGER);
DROP FUNCTION IF EXISTS {SCHEMA_NAME}.fn_format_csv_no_quotes(TEXT);
DROP FUNCTION IF EXISTS {SCHEMA_NAME}.fn_format_csv_quotes(TEXT);

-- Remove unused columns
ALTER TABLE test_runs
    DROP COLUMN IF EXISTS column_failed_ct,
    DROP COLUMN IF EXISTS column_warning_ct;

ALTER TABLE test_definitions
    DROP COLUMN IF EXISTS test_mode;

ALTER TABLE profiling_runs
    DROP COLUMN IF EXISTS anomaly_table_ct,
    DROP COLUMN IF EXISTS anomaly_column_ct;
