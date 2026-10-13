SET SEARCH_PATH TO {SCHEMA_NAME};

-- Whole-table sums that compare a column's values with a copy of them: the multiset hash of the values,
-- the epoch sum of a date column, and the keyed hash of each value with its row's key, together with
-- the table's inferred key column, repeated on every row of the table.
ALTER TABLE profile_results
    ADD COLUMN IF NOT EXISTS multiset_hash NUMERIC(38, 0),
    ADD COLUMN IF NOT EXISTS epoch_sum NUMERIC(38, 0),
    ADD COLUMN IF NOT EXISTS key_column_name VARCHAR(120),
    ADD COLUMN IF NOT EXISTS keyed_hash NUMERIC(38, 0);

ALTER TABLE table_groups
    ADD COLUMN IF NOT EXISTS profile_table_comparison BOOLEAN DEFAULT FALSE;
