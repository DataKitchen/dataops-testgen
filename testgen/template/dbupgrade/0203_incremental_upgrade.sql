SET SEARCH_PATH TO {SCHEMA_NAME};

-- v_latest_profile_results selects profile_results.*, so it pins every column it was
-- created with. Static metadata recreates it after the upgrade scripts run.
DROP VIEW IF EXISTS v_latest_profile_results CASCADE;

ALTER TABLE profile_results
    ADD COLUMN frequent_values JSONB,
    ADD COLUMN frequent_patterns JSONB;


-- One-shot converters for the two columns being replaced. A column converts only when
-- every entry in it reads cleanly; otherwise it is left NULL, since a profiled value
-- holding a line break or the field separator makes the entry boundaries ambiguous and
-- a partial conversion would misreport the frequencies. Those columns carry no
-- frequency data until their table group is profiled again.

CREATE FUNCTION fn_convert_freq_values(raw VARCHAR) returns JSONB
LANGUAGE SQL
IMMUTABLE
STRICT
as
$$
    WITH lines AS (
        SELECT rank, REGEXP_MATCH(line, '^\| (.*) \| ([0-9]+)$') AS parts
          FROM UNNEST(STRING_TO_ARRAY(raw, CHR(10))) WITH ORDINALITY AS t(line, rank)
    ),
    entries AS (
        SELECT rank, parts[1] AS value, parts[2]::BIGINT AS ct
          FROM lines
         WHERE parts IS NOT NULL
    ),
    built AS (
        SELECT (SELECT COUNT(*) FROM lines) = (SELECT COUNT(*) FROM entries) AS intact,
               JSONB_BUILD_OBJECT(
                   'values',
                   COALESCE(JSONB_AGG(JSONB_BUILD_OBJECT('value', value, 'ct', ct) ORDER BY rank)
                            FILTER (WHERE value !~ '^Other Values \([0-9]+\)$'), '[]'::JSONB))
               || COALESCE((SELECT JSONB_BUILD_OBJECT('other', JSONB_BUILD_OBJECT(
                                       'distinct_ct', (REGEXP_MATCH(value, '^Other Values \(([0-9]+)\)$'))[1]::BIGINT,
                                       'ct', ct))
                              FROM entries
                             WHERE value ~ '^Other Values \([0-9]+\)$'
                             LIMIT 1), '{}'::JSONB) AS frequent
          FROM entries
    )
    SELECT CASE WHEN intact THEN NULLIF(frequent, JSONB_BUILD_OBJECT('values', '[]'::JSONB)) END FROM built
$$;


CREATE FUNCTION fn_convert_patterns(raw VARCHAR) returns JSONB
LANGUAGE SQL
IMMUTABLE
STRICT
as
$$
    WITH parts AS (
        SELECT part, idx
          FROM UNNEST(STRING_TO_ARRAY(raw, ' | ')) WITH ORDINALITY AS t(part, idx)
    ),
    pairs AS (
        SELECT counted.idx, pattern.part AS value, counted.part::BIGINT AS ct
          FROM parts AS counted
          JOIN parts AS pattern ON pattern.idx = counted.idx + 1
         WHERE counted.idx % 2 = 1
           AND counted.part ~ '^[0-9]+$'
    ),
    built AS (
        SELECT (SELECT COUNT(*) FROM parts) = 2 * (SELECT COUNT(*) FROM pairs) AS intact,
               JSONB_BUILD_OBJECT(
                   'values',
                   COALESCE(JSONB_AGG(JSONB_BUILD_OBJECT('value', value, 'ct', ct) ORDER BY idx), '[]'::JSONB)) AS frequent
          FROM pairs
    )
    SELECT CASE WHEN intact THEN NULLIF(frequent, JSONB_BUILD_OBJECT('values', '[]'::JSONB)) END FROM built
$$;


UPDATE profile_results
   SET frequent_values = fn_convert_freq_values(top_freq_values),
       frequent_patterns = fn_convert_patterns(top_patterns)
 WHERE top_freq_values IS NOT NULL
    OR top_patterns IS NOT NULL;


DROP FUNCTION fn_convert_freq_values(VARCHAR);
DROP FUNCTION fn_convert_patterns(VARCHAR);

ALTER TABLE profile_results
    DROP COLUMN top_freq_values,
    DROP COLUMN top_patterns;


-- Accessors for the frequency analysis fields. Ranks are 1-based, most frequent first.

DROP FUNCTION IF EXISTS {SCHEMA_NAME}.fn_parsefreq(VARCHAR, INTEGER, INTEGER);
DROP FUNCTION IF EXISTS {SCHEMA_NAME}.fn_extract_top_values(TEXT);

-- Values only, pipe-joined in rank order, for the delimited-set helpers.
CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_value_list(frequent JSONB) returns VARCHAR
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT STRING_AGG(entry ->> 'value', '|' ORDER BY rank)
      FROM JSONB_ARRAY_ELEMENTS(COALESCE(frequent -> 'values', '[]'::JSONB))
           WITH ORDINALITY AS t(entry, rank)
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_value(frequent JSONB, rank INTEGER) returns VARCHAR
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT frequent -> 'values' -> (rank - 1) ->> 'value'
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_ct(frequent JSONB, rank INTEGER) returns BIGINT
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT (frequent -> 'values' -> (rank - 1) ->> 'ct')::BIGINT
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_size(frequent JSONB) returns INTEGER
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT JSONB_ARRAY_LENGTH(COALESCE(frequent -> 'values', '[]'::JSONB))
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_values(frequent JSONB) returns SETOF VARCHAR
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT entry ->> 'value'
      FROM JSONB_ARRAY_ELEMENTS(COALESCE(frequent -> 'values', '[]'::JSONB)) AS t(entry)
$$;


-- Case-insensitive. Matches value as a LIKE pattern, so '%x%' tests for a value
-- containing x. Use fn_frequent_like where case carries meaning, as it does in patterns.
CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_has(frequent JSONB, value VARCHAR) returns BOOLEAN
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT EXISTS (SELECT 1
                     FROM JSONB_ARRAY_ELEMENTS(COALESCE(frequent -> 'values', '[]'::JSONB)) AS t(entry)
                    WHERE entry ->> 'value' ILIKE value)
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_like(frequent JSONB, pattern VARCHAR) returns BOOLEAN
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT EXISTS (SELECT 1
                     FROM JSONB_ARRAY_ELEMENTS(COALESCE(frequent -> 'values', '[]'::JSONB)) AS t(entry)
                    WHERE entry ->> 'value' LIKE pattern)
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_display(frequent JSONB) returns VARCHAR
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT STRING_AGG(entry ->> 'value' || ' (' || (entry ->> 'ct') || ')', ', ' ORDER BY rank)
           || CASE WHEN frequent ? 'other'
                   THEN ', ' || (frequent -> 'other' ->> 'distinct_ct') || ' other values ('
                        || (frequent -> 'other' ->> 'ct') || ')'
                   ELSE '' END
      FROM JSONB_ARRAY_ELEMENTS(COALESCE(frequent -> 'values', '[]'::JSONB))
           WITH ORDINALITY AS t(entry, rank)
$$;
