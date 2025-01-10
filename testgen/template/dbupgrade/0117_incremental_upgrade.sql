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
-- |   Set up scoring aggregate functions
-- ==============================================================================

DROP AGGREGATE IF EXISTS sum_ln(double precision, double precision);
DROP FUNCTION IF EXISTS sum_ln_agg_state(sum_ln_state, double precision, double precision);
DROP FUNCTION IF EXISTS sum_ln_agg_final(sum_ln_state);
DROP TYPE IF EXISTS sum_ln_state;

CREATE TYPE sum_ln_state AS (
    log_sum double precision,
    pop_sum double precision
);


CREATE OR REPLACE FUNCTION sum_ln_agg_state(state sum_ln_state, probability double precision, population double precision)
RETURNS sum_ln_state AS $$
BEGIN
    -- Initialize log-sum (state[0]) to 0 if NULL
    IF state IS NULL THEN
        state := (0,0);
    END IF;

    -- Handle edge cases: null/zero population, null/invalid/extremely high probabilities
    IF population IS NULL OR population <= 0
          OR probability IS NULL OR probability <= 0
          OR probability > 0.999999 THEN
        -- Log-sum remains unchanged, but add valid population
        RETURN (state.log_sum, state.pop_sum + COALESCE(population, 0))::sum_ln_state;
    END IF;

    -- Update log-sum and total population for valid inputs
    RETURN (
        state.log_sum + LN(1 - probability)*population,
        state.pop_sum + population
    )::sum_ln_state;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION sum_ln_agg_final(state sum_ln_state)
RETURNS double precision AS $$
BEGIN
    -- Avoid division by zero or incorrect log-sum results
    IF state.pop_sum <= 0 THEN
        -- If total population is zero, return 1 (no probability adjustment)
        RETURN 1;
    END IF;

    -- Compute weighted probability in log-space
    RETURN EXP(state.log_sum / state.pop_sum);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE AGGREGATE sum_ln (double precision, double precision) (
    SFUNC = sum_ln_agg_state,
    STYPE = sum_ln_state, -- Stores log-sum and population
    INITCOND  = '(0,0)',  -- Initial state: log-sum = 0, total population = 0
    FINALFUNC = sum_ln_agg_final
);
