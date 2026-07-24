SET SEARCH_PATH TO {SCHEMA_NAME};

-- Column profiling's frequency pass now writes its results (top_freq_values,
-- distinct_value_hash) straight to profile_results, so this staging table has no
-- writer. Its rows were transient with no run linkage; drop it.
DROP TABLE IF EXISTS stg_secondary_profile_updates;
