SET SEARCH_PATH TO {SCHEMA_NAME};

-- Profiling reads only Alpha columns on the sample, so only their rows keep a sample ratio.
UPDATE profile_results
   SET sample_ratio = NULL
 WHERE sample_ratio IS NOT NULL
   AND general_type IS DISTINCT FROM 'A';
