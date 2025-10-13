-- ==============================================================================
-- |   This recreates the constraints for the test metadata tables after being imported by yaml
-- ==============================================================================

SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_templates
   ADD CONSTRAINT test_templates_test_types_test_type_fk
      FOREIGN KEY (test_type) REFERENCES test_types;

ALTER TABLE test_results
   ADD CONSTRAINT test_results_test_types_test_type_fk
      FOREIGN KEY (test_type) REFERENCES test_types;

ALTER TABLE cat_test_conditions
   ADD CONSTRAINT cat_test_conditions_cat_tests_test_type_fk
      FOREIGN KEY (test_type) REFERENCES test_types;
