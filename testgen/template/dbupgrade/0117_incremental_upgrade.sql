SET SEARCH_PATH TO {SCHEMA_NAME};

-- New Column
ALTER TABLE profile_anomaly_types
   ADD COLUMN dq_dimension VARCHAR(50);

ALTER TABLE profile_results
   ADD COLUMN column_id UUID;

ALTER TABLE data_column_chars
   ADD COLUMN valid_profile_issue_ct BIGINT DEFAULT 0,
   ADD COLUMN valid_test_issue_ct    BIGINT DEFAULT 0;

-- ==============================================================================
-- |   Scoring Prevalence calculation functions
-- ==============================================================================

CREATE OR REPLACE FUNCTION fn_normal_cdf(z_score DOUBLE PRECISION)
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

CREATE OR REPLACE FUNCTION fn_eval(expression TEXT) RETURNS FLOAT
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

   -- Remove all allowed tokens from the validation expression, treating 'FLOAT' as a keyword
   invalid_parts := regexp_replace(
      expression,
      E'(\\mGREATEST|LEAST|ABS|FN_NORMAL_CDF|DATEDIFF|DAY|FLOAT|NULLIF)\\M|[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?|[+\\-*/(),\\\'":]+|\\s+',
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

DROP AGGREGATE IF EXISTS sum_ln(double precision, double precision);
DROP FUNCTION IF EXISTS sum_ln_agg_state(sum_ln_state, double precision, double precision);
DROP FUNCTION IF EXISTS sum_ln_agg_final(sum_ln_state);
DROP TYPE IF EXISTS sum_ln_state; -- Older version had this

CREATE OR REPLACE FUNCTION sum_ln_agg_state(
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


CREATE OR REPLACE FUNCTION sum_ln_agg_final(
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


DROP AGGREGATE IF EXISTS sum_ln (double precision);

CREATE AGGREGATE sum_ln (double precision) (
    SFUNC     = sum_ln_agg_state,
    STYPE     = double precision,
    FINALFUNC = sum_ln_agg_final,
    INITCOND  = '0'
);
