-- Get Freqs for selected columns
-- One row per top value, ordered by rank. A trailing row with a NULL value carries the
-- combined count of the values past the top 10, and how many distinct values it covers.
-- Every row also carries sample_value_ct, the number of non-null values the read held, blank ones
-- included. Blank values are ranked after every other value so that they never reach the output.
WITH target_table AS (
-- TG-IF do_sample_bool
    SELECT {COL_VALUE} AS "{COL_NAME}" FROM "{DATA_SCHEMA}"."{DATA_TABLE}" TABLESAMPLE ({SAMPLE_PERCENT_CALC} PERCENT) {TABLE_HINT}
-- TG-ELSE
    SELECT {COL_VALUE} AS "{COL_NAME}" FROM "{DATA_SCHEMA}"."{DATA_TABLE}" {TABLE_HINT}
-- TG-ENDIF
    ),
ranked_vals
AS
    (SELECT "{COL_NAME}" AS val,
            COUNT(*) AS  ct,
            ROW_NUMBER() OVER (ORDER BY CASE WHEN "{COL_NAME}" > ' ' THEN 0 ELSE 1 END, COUNT(*) DESC, CAST("{COL_NAME}" AS NVARCHAR(4000)) COLLATE Latin1_General_100_BIN2) AS rn,
            SUM(COUNT_BIG(*)) OVER () AS sample_value_ct
     FROM target_table
     WHERE "{COL_NAME}" IS NOT NULL
     GROUP BY "{COL_NAME}"
    ),
grouped_vals
AS (
    SELECT CASE WHEN rn <= 10 THEN val END AS top_val, ct, rn, sample_value_ct
    FROM ranked_vals
    WHERE val > ' '
    ),
-- The hash is over the UTF-8 bytes of the distinct values, which SQL Server 2017 has no collation
-- to produce, so they are built from the code points: one row per UTF-16 code unit, a surrogate
-- pair read as one code point, each written out as its UTF-8 bytes in hex. Values are made
-- distinct as binary because string comparison ignores trailing spaces, even under BIN2.
hash_input
AS (
    SELECT CASE WHEN COUNT(*) <= 70 THEN STRING_AGG(val, N'|') WITHIN GROUP (ORDER BY val, DATALENGTH(val)) END AS agg
    FROM (SELECT CAST(bin AS NVARCHAR(MAX)) COLLATE Latin1_General_100_BIN2 AS val
            FROM (SELECT DISTINCT CAST(CAST("{COL_NAME}" AS NVARCHAR(MAX)) AS VARBINARY(MAX)) AS bin
                    FROM target_table
                   WHERE "{COL_NAME}" IS NOT NULL) distinct_bins) distinct_vals
    ),
hash_code_points
AS (
    SELECT pos,
           CASE WHEN unit BETWEEN 55296 AND 56319 THEN 65536 + (unit - 55296) * 1024 + (next_unit - 56320)
                ELSE unit END AS cp
    FROM (SELECT p.pos, UNICODE(SUBSTRING(h.agg, p.pos, 1)) AS unit, UNICODE(SUBSTRING(h.agg, p.pos + 1, 1)) AS next_unit
            FROM hash_input h
           CROSS JOIN (SELECT TOP (SELECT ISNULL(DATALENGTH(agg) / 2, 0) FROM hash_input)
                              ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS pos
                         FROM sys.all_columns a CROSS JOIN sys.all_columns b) p) units
    WHERE unit NOT BETWEEN 56320 AND 57343
    ),
hash_bytes
AS (
    SELECT pos,
           CASE WHEN cp < 128 THEN CONVERT(VARCHAR(8), CAST(cp AS BINARY(1)), 2)
                WHEN cp < 2048 THEN CONVERT(VARCHAR(8), CAST(192 + cp / 64 AS BINARY(1)) + CAST(128 + cp % 64 AS BINARY(1)), 2)
                WHEN cp < 65536 THEN CONVERT(VARCHAR(8), CAST(224 + cp / 4096 AS BINARY(1)) + CAST(128 + cp / 64 % 64 AS BINARY(1))
                                                       + CAST(128 + cp % 64 AS BINARY(1)), 2)
                ELSE CONVERT(VARCHAR(8), CAST(240 + cp / 262144 AS BINARY(1)) + CAST(128 + cp / 4096 % 64 AS BINARY(1))
                                       + CAST(128 + cp / 64 % 64 AS BINARY(1)) + CAST(128 + cp % 64 AS BINARY(1)), 2)
           END AS hex
    FROM hash_code_points
    ),
value_hash
AS (
    SELECT CASE WHEN (SELECT agg FROM hash_input) IS NOT NULL
                THEN LOWER(CONVERT(VARCHAR(32), HASHBYTES('MD5',
                         ISNULL(CONVERT(VARBINARY(MAX), STRING_AGG(CAST(hex AS VARCHAR(MAX)), '') WITHIN GROUP (ORDER BY pos), 2), 0x)), 2))
           END AS distinct_value_hash
    FROM hash_bytes
    )
SELECT top_val AS value,
       SUM(ct) AS value_ct,
       MIN(rn) AS value_rank,
       CASE WHEN MIN(rn) > 10 THEN COUNT(*) END AS other_distinct_ct,
       MAX(sample_value_ct) AS sample_value_ct,
       (SELECT distinct_value_hash FROM value_hash) AS distinct_value_hash
FROM grouped_vals
GROUP BY top_val
ORDER BY 3;

-- Convert function has style = 2 : The characters 0x aren't added to the left of the converted result for style 2.
