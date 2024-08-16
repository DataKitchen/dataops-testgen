SET SEARCH_PATH TO {SCHEMA_NAME};

-- Step 1: Drop everything that depends on the current state

DROP TABLE execution_queue;
DROP VIEW v_test_results;
ALTER TABLE test_definitions DROP CONSTRAINT test_definitions_test_suites_project_code_test_suite_fk;
ALTER TABLE test_results DROP CONSTRAINT test_results_test_suites_project_code_test_suite_fk;
ALTER TABLE test_suites DROP CONSTRAINT test_suites_project_code_test_suite_pk;
DROP INDEX ix_td_pc_stc_tst;


-- Step 2: Adjust the test definition table

    UPDATE test_definitions
       SET test_suite_id = ts.id
      FROM test_definitions td
INNER JOIN test_suites AS ts ON td.test_suite = ts.test_suite AND td.project_code = ts.project_code
     WHERE td.test_suite_id is NULL;

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

CREATE VIEW v_test_results AS
     SELECT p.project_name,
            ts.test_suite,
            tg.table_groups_name,
            cn.connection_name, cn.project_host, cn.sql_flavor,
            tt.dq_dimension,
            r.schema_name, r.table_name, r.column_names,
            r.test_time as test_date,
            r.test_type,  tt.id as test_type_id, tt.test_name_short, tt.test_name_long,
            r.test_description,
            tt.measure_uom, tt.measure_uom_description,
            c.test_operator,
            r.threshold_value::NUMERIC(16, 5) as threshold_value,
            r.result_measure::NUMERIC(16, 5),
            r.result_status,
            r.input_parameters,
            r.result_message,
            CASE WHEN result_code <> 1 THEN r.severity END as severity,
            CASE
              WHEN result_code <> 1 THEN r.disposition
                 ELSE 'Passed'
            END AS disposition,
            r.result_code as passed_ct,
            (1 - r.result_code)::INTEGER as exception_ct,
            CASE
              WHEN result_status = 'Warning'
               AND result_message NOT ILIKE 'ERROR - TEST COLUMN MISSING%' THEN 1
            END::INTEGER as warning_ct,
            CASE
              WHEN result_status = 'Failed'
               AND result_message NOT ILIKE 'ERROR - TEST COLUMN MISSING%' THEN 1
            END::INTEGER as failed_ct,
            CASE
              WHEN result_message ILIKE 'ERROR - TEST COLUMN MISSING%' THEN 1
            END AS execution_error_ct,
            r.project_code,
            r.table_groups_id,
            r.id as test_result_id, c.id as connection_id,
            r.test_suite_id,
            r.test_definition_id as test_definition_id_runtime,
            CASE
              WHEN r.auto_gen = TRUE THEN d.id
                                     ELSE r.test_definition_id
            END as test_definition_id_current,
            r.test_run_id as test_run_id,
            r.auto_gen
       FROM test_results r
 INNER JOIN test_types tt
         ON r.test_type = tt.test_type
  LEFT JOIN test_definitions d
         ON r.test_suite_id = d.test_suite_id
        AND r.table_name = d.table_name
        AND r.column_names = COALESCE(d.column_name, 'N/A')
        AND r.test_type = d.test_type
        AND r.auto_gen = TRUE
        AND d.last_auto_gen_date IS NOT NULL
 INNER JOIN test_suites ts
         ON r.test_suite_id = ts.id
 INNER JOIN projects p
         ON r.project_code = p.project_code
 INNER JOIN table_groups tg
         ON r.table_groups_id = tg.id
 INNER JOIN connections cn
         ON tg.connection_id = cn.connection_id
  LEFT JOIN cat_test_conditions c
         ON cn.sql_flavor = c.sql_flavor
        AND r.test_type = c.test_type;
