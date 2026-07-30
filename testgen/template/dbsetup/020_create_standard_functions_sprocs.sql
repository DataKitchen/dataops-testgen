SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.datediff(difftype character varying, firstdate timestamp without time zone, seconddate timestamp without time zone) returns bigint
    language plpgsql
as
$$
   BEGIN
      RETURN
      CASE
        WHEN UPPER(difftype) IN ('DAY', 'DD')
              THEN DATE_PART('day', seconddate - firstdate)
        WHEN UPPER(difftype) IN ('WEEK','WK')
              THEN (DATE_TRUNC('week', seconddate)::DATE - DATE_TRUNC('week', firstdate)::DATE) / 7
        WHEN UPPER(difftype) IN ('MON', 'MM')
              THEN 12 * (DATE_PART('year', seconddate) - DATE_PART('year', firstdate))
                    + (DATE_PART('month', seconddate) - DATE_PART('month', firstdate))
        WHEN UPPER(difftype) IN ('QUARTER', 'QTR')
              THEN 4 * (DATE_PART('year', seconddate) - DATE_PART('year', firstdate))
                    + (DATE_PART('qtr', seconddate) - DATE_PART('month', firstdate))
        WHEN UPPER(difftype) IN ('YEAR', 'YY')
              THEN DATE_PART('year', seconddate) - DATE_PART('year', firstdate)
      END;
   END;
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_charcount(instring character varying, searchstring character varying) returns bigint
    language plpgsql
as
$$
   BEGIN
      RETURN (CHAR_LENGTH(instring) - CHAR_LENGTH(REPLACE(instring, searchstring, ''))) / CHAR_LENGTH(searchstring);
   END;
$$;


-- Accessors for the frequency analysis fields on profile_results
-- (frequent_values, frequent_patterns). Ranks are 1-based, most frequent first.

DROP FUNCTION IF EXISTS {SCHEMA_NAME}.fn_parsefreq(VARCHAR, INTEGER, INTEGER);

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


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_pct(numerator NUMERIC, denominator NUMERIC, decs INTEGER DEFAULT 0) returns NUMERIC
    language plpgsql
as
$$
   BEGIN
      RETURN ROUND((100.0 * numerator/denominator), decs);
   END;
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_quote_literal_escape(var_value varchar, sql_flavor varchar) RETURNS varchar
    LANGUAGE plpgsql
AS
$$
DECLARE
    escaped_value         varchar;
    lower_case_sql_flavor varchar;
BEGIN
    lower_case_sql_flavor := LOWER(sql_flavor);

    IF lower_case_sql_flavor IN ('postgres', 'postgresql') THEN
        escaped_value := QUOTE_LITERAL(var_value);
    ELSIF lower_case_sql_flavor IN ('redshift', 'redshift_spectrum', 'snowflake') THEN
        escaped_value := TRIM(LEADING 'E' FROM QUOTE_LITERAL(var_value));
    ELSIF lower_case_sql_flavor = 'mssql' THEN
        escaped_value := '''' || REPLACE(var_value, '''', '''''') || '''';
    ELSIF lower_case_sql_flavor = 'databricks' THEN
        escaped_value := '''' || REPLACE(REPLACE(var_value, '\', '\\'), '''', '\''') || '''';
    ELSE
        RAISE EXCEPTION 'Invalid sql_flavor name: %', sql_flavor;
    END IF;

    RETURN escaped_value;
END;
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_format_csv_no_quotes(str_csv TEXT) returns TEXT
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT
        REGEXP_REPLACE(
                       REGEXP_REPLACE(str_csv::VARCHAR, '''', '', 'g'),  -- Remove single quotes
                       '\s*,\s*',  -- Match comma, with or without surrounding spaces
                       ', ',       -- Replace with comma followed by a space
                       'g'         -- Global replace
                      ) AS formatted_value
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_format_csv_quotes(str_csv TEXT) returns TEXT
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT
       '''' || REGEXP_REPLACE(str_csv::VARCHAR, '\s*,\s*', ''', ''', 'g') || ''''
   AS formatted_value
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_count_intersecting_items(list1 VARCHAR, list2 VARCHAR, separator VARCHAR)
RETURNS BIGINT AS $$
SELECT COUNT(*)
FROM (
    SELECT unnest(string_to_array(list1, separator)) AS element
    INTERSECT
    SELECT unnest(string_to_array(list2, separator))
) AS intersection
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_extract_intersecting_items(list1 VARCHAR, list2 VARCHAR, separator VARCHAR)
RETURNS VARCHAR AS $$
SELECT STRING_AGG(DISTINCT element, separator) as shared_vals
FROM (
    SELECT unnest(string_to_array(list1, separator)) AS element
    INTERSECT
    SELECT unnest(string_to_array(list2, separator))
) AS intersection
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_extract_distinct_items(list VARCHAR, separator VARCHAR)
RETURNS VARCHAR AS $$
SELECT STRING_AGG(DISTINCT element, separator) as distinct_items
FROM (
    SELECT unnest(string_to_array(list, separator)) AS element
) AS all_items
$$ LANGUAGE sql;


-- Values only, pipe-joined in rank order, for the delimited-set helpers above.
CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_frequent_value_list(frequent JSONB) returns VARCHAR
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT STRING_AGG(entry ->> 'value', '|' ORDER BY rank)
      FROM JSONB_ARRAY_ELEMENTS(COALESCE(frequent -> 'values', '[]'::JSONB))
           WITH ORDINALITY AS t(entry, rank)
$$;

-- ==============================================================================
-- |   Scoring Prevalence calculation functions
-- ==============================================================================

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_normal_cdf(z_score DOUBLE PRECISION)
RETURNS DOUBLE PRECISION AS
$$
/*
    This function calculates the cumulative distribution function (CDF)
    for the standard normal distribution for a given Z-score using
    the Abramowitz and Stegun approximation method. It returns the
    probability that a standard normal variable is less than or equal
    to the given Z-score.

    The approximation formula uses a series expansion to estimate the
    CDF, which is accurate for most practical purposes.

    To estimate the count of observations that fall outside a certain Z-score
    (both above and below), you can use the `normal_cdf()` function. For a
    total number of observations N, the proportion of values outside the Z-score
    is given by:  2 * (1 - normal_cdf(ABS(Z)))

    This gives the proportion of values greater than the positive Z-score and
    less than the negative Z-score combined. To get the estimated count of
    observations, multiply this proportion by N:   N * 2 * (1 - normal_cdf(ABS(Z)))
    It handles extreme Z-scores by assuming a result of 0 for very low Z-scores
    and 1 for very high Z-scores beyond a defined threshold.
*/
DECLARE
    threshold DOUBLE PRECISION := 6.0; -- Threshold for extreme Z-scores
    t DOUBLE PRECISION;
    cdf DOUBLE PRECISION;
BEGIN
    -- Handle extreme Z-scores
    IF z_score <= -threshold THEN
        RETURN 0.0; -- Near-zero probability for very low Z-scores
    ELSIF z_score >= threshold THEN
        RETURN 1.0; -- Near-one probability for very high Z-scores
    END IF;

    -- Abramowitz and Stegun approximation for normal cases
    t := 1.0 / (1.0 + 0.2316419 * ABS(z_score));

    cdf := (1.0 / SQRT(2 * PI())) * EXP(-0.5 * z_score * z_score) *
           (0.319381530 * t
            - 0.356563782 * t * t
            + 1.781477937 * t * t * t
            - 1.821255978 * t * t * t * t
            + 1.330274429 * t * t * t * t * t);

    -- Return the CDF based on the sign of the Z-score
    IF z_score >= 0 THEN
        RETURN 1.0 - cdf;
    ELSE
        RETURN cdf;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_eval(expression TEXT) RETURNS FLOAT
AS
$$
DECLARE
   result FLOAT;
   invalid_parts TEXT;
BEGIN
   -- Check the modified expression for invalid characters, allowing colons
   IF expression ~* E'[^0-9+\\-*/(),.\\sA-Z_:e\\\'"]' THEN
      RAISE EXCEPTION 'Invalid characters detected in expression: %', expression;
   END IF;

   -- Check for dangerous PostgreSQL-specific keywords
   IF expression ~* E'\b(DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|GRANT|REVOKE|COPY|EXECUTE|CREATE|COMMENT|SECURITY|WITH|SET ROLE|SET SESSION|DO|CALL|--|/\\*|;|pg_read_file|pg_write_file|pg_terminate_backend)\b' THEN
      RAISE EXCEPTION 'Invalid expression: dangerous statement detected';
   END IF;

   -- Remove all allowed tokens from the validation expression, treating 'FLOAT' as a keyword.
   -- Numeric pattern accepts leading-dot decimals (e.g. ".733") that Oracle emits
   -- when converting NUMBER values with |x| < 1 to VARCHAR2.
   invalid_parts := regexp_replace(
      expression,
      E'(\\mGREATEST|LEAST|ABS|FN_NORMAL_CDF|DATEDIFF|DAY|FLOAT|NULLIF)\\M|([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][+-]?[0-9]+)?|[+\\-*/(),\\\'":]+|\\s+',
      '',
      'gi'
   );

   -- If anything is left in the validation expression, it's invalid
   IF invalid_parts <> '' THEN
      RAISE EXCEPTION 'Invalid expression contains invalid tokens "%" in expression: %', invalid_parts, expression;
   END IF;

   -- Use the original expression (with ::FLOAT) for execution
   EXECUTE format('SELECT (%s)::FLOAT', expression) INTO result;

   RETURN result;
END;
$$
LANGUAGE plpgsql;

-- ==============================================================================
-- |   Set up scoring aggregate functions
-- ==============================================================================

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.sum_ln_agg_state(
    state       double precision,
    probability double precision
)
RETURNS double precision
AS $$
BEGIN

    -- If this is the first row (or state is NULL for some reason), initialize
    IF state IS NULL THEN
        state := 0;
    END IF;

    -- Handle edge cases: null/zero population, null/invalid/extremely high probabilities
    IF probability IS NULL
       OR probability <= 0
       OR probability > 0.999999
    THEN
        RETURN state; -- do not update the log-sum
    END IF;

    -- Otherwise accumulate LN(1 - probability)
    RETURN state + LN(1 - probability);

END;
$$ LANGUAGE plpgsql IMMUTABLE;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.sum_ln_agg_final(
    state double precision
)
RETURNS double precision
AS $$
BEGIN

    -- If never updated, or all skipped => return 1 (no effect)
    IF state IS NULL THEN
        RETURN 1;
    END IF;

    -- Convert the total logs to a product
    RETURN EXP(state);

END;
$$ LANGUAGE plpgsql IMMUTABLE;


DROP AGGREGATE IF EXISTS {SCHEMA_NAME}.sum_ln (double precision) CASCADE;

CREATE AGGREGATE {SCHEMA_NAME}.sum_ln (double precision) (
    SFUNC     = sum_ln_agg_state,
    STYPE     = double precision,
    FINALFUNC = sum_ln_agg_final,
    INITCOND  = '0'
);
