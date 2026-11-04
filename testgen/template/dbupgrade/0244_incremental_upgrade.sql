SET SEARCH_PATH TO {SCHEMA_NAME};

-- Test suite and contract names become unique within a project. Where a name is shared, the suite
-- that ran first keeps it and every other one gets the first free "<name> (N)", N counting from 2.
DO $$
DECLARE
    dup       RECORD;
    n         INTEGER;
    suffix    TEXT;
    candidate TEXT;
BEGIN
    FOR dup IN
        WITH ranked AS (
            SELECT ts.id,
                   ts.project_code,
                   ts.test_suite,
                   ROW_NUMBER() OVER (
                       PARTITION BY ts.project_code, ts.test_suite
                       ORDER BY first_run.started NULLS LAST, ts.id
                   ) AS rank
              FROM test_suites ts
              LEFT JOIN LATERAL (
                  SELECT MIN(tr.test_starttime) AS started
                    FROM test_runs tr
                   WHERE tr.test_suite_id = ts.id
              ) first_run ON TRUE
             WHERE ts.suite_type IN ('regular', 'contract')
        )
        SELECT id, project_code, test_suite
          FROM ranked
         WHERE rank > 1
         ORDER BY project_code, test_suite, rank
    LOOP
        n := 2;
        LOOP
            suffix := ' (' || n || ')';
            candidate := TRIM(LEFT(dup.test_suite, 200 - LENGTH(suffix)) || suffix);
            EXIT WHEN NOT EXISTS (
                SELECT 1
                  FROM test_suites
                 WHERE project_code = dup.project_code
                   AND test_suite = candidate
                   AND suite_type IN ('regular', 'contract')
            );
            n := n + 1;
        END LOOP;
        UPDATE test_suites SET test_suite = candidate WHERE id = dup.id;
    END LOOP;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS test_suites_name_unique
    ON test_suites (project_code, test_suite)
    WHERE suite_type IN ('regular', 'contract');
