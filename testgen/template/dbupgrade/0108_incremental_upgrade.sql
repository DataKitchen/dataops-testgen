SET SEARCH_PATH TO {SCHEMA_NAME};

-- Step 1: Drop everything that depends on the current state

DROP TABLE execution_queue;
DROP VIEW IF EXISTS v_test_results;
ALTER TABLE test_definitions DROP CONSTRAINT test_definitions_test_suites_project_code_test_suite_fk;
ALTER TABLE test_results DROP CONSTRAINT test_results_test_suites_project_code_test_suite_fk;
ALTER TABLE test_suites DROP CONSTRAINT test_suites_project_code_test_suite_pk;
DROP INDEX ix_td_pc_stc_tst;


-- Step 2: Adjust the test definition table

    UPDATE test_definitions
       SET test_suite_id = ts.id
      FROM test_definitions td
INNER JOIN test_suites AS ts ON td.test_suite = ts.test_suite AND td.project_code = ts.project_code
     WHERE td.test_suite_id is NULL
       AND test_definitions.id = td.id;

ALTER TABLE test_definitions ALTER COLUMN test_suite_id SET NOT NULL;

-- Step 3: Re-create the constraints

ALTER TABLE test_suites ADD CONSTRAINT test_suites_id_pk PRIMARY KEY (id);
ALTER TABLE test_definitions ADD CONSTRAINT test_definitions_test_suites_test_suite_id_fk
    FOREIGN KEY (test_suite_id) REFERENCES test_suites;
ALTER TABLE test_results ADD CONSTRAINT test_results_test_suites_test_suite_id_fk
    FOREIGN KEY (test_suite_id) REFERENCES test_suites;

-- Step 4: Clean up

ALTER TABLE test_definitions DROP COLUMN test_suite;
ALTER TABLE test_definitions DROP COLUMN project_code;

-- Step 5: Re-create views and indexes

CREATE INDEX ix_td_pc_stc_tst
   ON test_definitions(test_suite_id, schema_name, table_name, column_name, test_type);
