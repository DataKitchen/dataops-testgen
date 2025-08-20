SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE test_runs ADD COLUMN log_ct INTEGER;

DROP VIEW IF EXISTS v_test_results;

ALTER TABLE test_types ADD COLUMN result_visualization VARCHAR(50) DEFAULT 'line_chart';
ALTER TABLE test_types ADD COLUMN result_visualization_params TEXT DEFAULT NULL;
