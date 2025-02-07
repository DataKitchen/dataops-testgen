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
