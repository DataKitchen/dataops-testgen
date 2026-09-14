SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_types ADD COLUMN IF NOT EXISTS ai_redact_values BOOLEAN NOT NULL DEFAULT FALSE;

-- Flags the test types whose result_measure can carry an actual source-data value
-- rather than a violation count or a normalized statistic. The YAML importer also
-- sets these on every install and upgrade; the statement here keeps the migration
-- self-sufficient for anyone applying it directly.
--
--   LOV_All      measure is STRING_AGG(DISTINCT column, '|') — a literal list of column values
--   Recency      measure is DATEDIFF(MAX(column), run_date) — invertible to MAX(column)
--   Dec_Trunc    measure is SUM(ROUND(ABS(column % 1), 5)) — leaks the fractional part on a
--                single-row table
--   Metric_Trend measure is the user's own aggregate expression, which may be MAX(column)
--   CUSTOM       measure is whatever the user's SQL returns
--
-- Table_Freshness is deliberately absent: its measure is a 0/1 change-detected flag. The
-- fingerprint it compares against lives in result_signal and lower_tolerance, neither of
-- which is surfaced as a measure. Freshness_Trend does measure a fingerprint, but an MD5
-- conveys no column value.
UPDATE test_types
   SET ai_redact_values = TRUE
 WHERE test_type IN (
          'LOV_All',
          'Recency',
          'Dec_Trunc',
          'Metric_Trend',
          'CUSTOM'
       );

-- An uploaded type carries arbitrary measure SQL, so it is withheld unless its file
-- says otherwise — the same choice the upload path makes for new uploads. Types
-- uploaded before this column existed have no packaged YAML for the importer to
-- revisit, so they are backfilled here.
UPDATE test_types
   SET ai_redact_values = TRUE
 WHERE uploaded_version IS NOT NULL;
