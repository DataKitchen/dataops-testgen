SET SEARCH_PATH TO {SCHEMA_NAME};

-- Max Threads defaults per connection type. A connection stored at the former default, 4, or with no
-- value takes its type's default; a value the user chose otherwise is kept.
UPDATE connections
   SET max_threads = CASE
           WHEN COALESCE(sql_flavor_code, sql_flavor) IN ('duckdb', 'files', 's3', 'azure_blob') THEN 1
           WHEN COALESCE(sql_flavor_code, sql_flavor) IN ('mssql', 'azure_mssql', 'redshift', 'oracle') THEN 2
           WHEN COALESCE(sql_flavor_code, sql_flavor) = 'bigquery' THEN 8
           ELSE 4
       END
 WHERE max_threads = 4 OR max_threads IS NULL;

ALTER TABLE connections ALTER COLUMN max_threads DROP DEFAULT;
ALTER TABLE connections ALTER COLUMN max_threads SET NOT NULL;
