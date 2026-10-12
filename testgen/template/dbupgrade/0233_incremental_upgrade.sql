SET SEARCH_PATH TO {SCHEMA_NAME};

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

    -- Null or non-positive probabilities affect no rows
    IF probability IS NULL OR probability <= 0 THEN
        RETURN state; -- do not update the log-sum
    END IF;

    -- A probability of 1 or more affects every row, so the product of (1 - p) is 0
    IF probability >= 1 THEN
        RETURN '-Infinity'::double precision;
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

    IF state = '-Infinity'::double precision THEN
        RETURN 0;
    END IF;

    -- Convert the total logs to a product
    RETURN EXP(state);

END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- Overlapping refreshes of one scorecard could each insert a full set of result and breakdown rows.
-- Collapse them to one set before enforcing the key, otherwise adding it would abort the upgrade.
DELETE FROM score_definition_results
 WHERE definition_id IS NULL;

DELETE FROM score_definition_results a
    USING score_definition_results b
    WHERE a.ctid < b.ctid
      AND a.definition_id = b.definition_id
      AND a.category = b.category;

DO $$
BEGIN
   IF NOT EXISTS (
      SELECT 1 FROM pg_constraint WHERE conname = 'score_definition_results_pk'
   ) THEN
      ALTER TABLE score_definition_results
         ADD CONSTRAINT score_definition_results_pk PRIMARY KEY (definition_id, category);
   END IF;
END $$;

DELETE FROM score_definition_results_breakdown
 WHERE id IN (
    SELECT id
      FROM (SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY definition_id, category, score_type, table_groups_id, table_name, column_name,
                                    dq_dimension, impact_dimension, semantic_data_type, table_groups_name,
                                    data_location, data_source, source_system, source_process, business_domain,
                                    stakeholder_group, transform_level, data_product, data_classification,
                                    impact, score, issue_ct
                   ) AS copy_number
              FROM score_definition_results_breakdown) copies
     WHERE copy_number > 1
 );

CREATE INDEX IF NOT EXISTS ix_sdrb_definition
    ON score_definition_results_breakdown (definition_id);

-- At most one project score refresh waits per project; further requests merge into it.
CREATE UNIQUE INDEX IF NOT EXISTS uix_job_executions_pending_project_scores
    ON job_executions (project_code)
    WHERE job_key = 'refresh-project-scores' AND status = 'pending';
