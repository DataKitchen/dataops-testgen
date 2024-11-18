SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_types
   ADD COLUMN dq_score_prevalence_formula TEXT,
   ADD COLUMN dq_score_risk_factor        TEXT;

ALTER TABLE test_suites
   ADD COLUMN last_complete_test_run_id UUID,
   ADD COLUMN dq_score_exclude BOOLEAN default FALSE;

ALTER TABLE profile_anomaly_types
   ADD COLUMN dq_score_prevalence_formula TEXT,
   ADD COLUMN dq_score_risk_factor TEXT;

ALTER TABLE profile_anomaly_results
   ADD COLUMN dq_prevalence FLOAT;

ALTER TABLE profiling_runs
   ADD COLUMN dq_affected_data_points BIGINT,
   ADD COLUMN dq_total_data_points BIGINT,
   ADD COLUMN dq_score_profiling FLOAT;

ALTER TABLE test_results
   ADD COLUMN dq_prevalence FLOAT,
   ADD COLUMN dq_record_ct  BIGINT;

ALTER TABLE test_runs
   ADD COLUMN dq_affected_data_points BIGINT,
   ADD COLUMN dq_total_data_points BIGINT,
   ADD COLUMN dq_score_test_run FLOAT;

ALTER TABLE table_groups
   ADD COLUMN last_complete_profile_run_id UUID,
   ADD COLUMN dq_score_profiling FLOAT,
   ADD COLUMN dq_score_testing FLOAT;

ALTER TABLE data_table_chars
   ADD COLUMN last_complete_profile_run_id UUID,
   ADD COLUMN dq_score_profiling FLOAT,
   ADD COLUMN dq_score_testing FLOAT;

ALTER TABLE data_column_chars
   ADD COLUMN last_complete_profile_run_id UUID,
   ADD COLUMN dq_score_profiling FLOAT,
   ADD COLUMN dq_score_testing FLOAT;


ALTER TABLE profile_results
   ADD COLUMN upper_case_ct BIGINT,
   ADD COLUMN lower_case_ct BIGINT,
   ADD COLUMN non_alpha_ct BIGINT,
   ADD COLUMN mixed_case_ct BIGINT GENERATED ALWAYS AS ( value_ct - upper_case_ct - lower_case_ct - non_alpha_ct ) STORED,
   ADD COLUMN before_100yr_date_ct BIGINT,
   ADD COLUMN distant_future_date_ct BIGINT;


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
*/
DECLARE
    t DOUBLE PRECISION;
    cdf DOUBLE PRECISION;
BEGIN
    t := 1.0 / (1.0 + 0.2316419 * ABS(z_score));

    cdf := (1.0 / SQRT(2 * PI())) * EXP(-0.5 * z_score * z_score) *
           (0.319381530 * t
            - 0.356563782 * t * t
            + 1.781477937 * t * t * t
            - 1.821255978 * t * t * t * t
            + 1.330274429 * t * t * t * t * t);

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
      E'(\\mGREATEST|LEAST|ABS|FN_NORMAL_CDF|DATEDIFF|DAY|FLOAT)\\M|[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?|[+\\-*/(),\\\'":]+|\\s+',
      '',
      'gi'
   );

   -- If anything is left in the validation expression, it's invalid
   IF invalid_parts <> '' THEN
      RAISE EXCEPTION 'Invalid tokens "%" in expression: %', invalid_parts, expression;
   END IF;

   -- Use the original expression (with ::FLOAT) for execution
   EXECUTE format('SELECT (%s)::FLOAT', expression) INTO result;

   RETURN result;
END;
$$
LANGUAGE plpgsql;
