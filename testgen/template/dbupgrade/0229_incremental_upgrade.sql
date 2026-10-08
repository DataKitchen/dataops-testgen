SET SEARCH_PATH TO {SCHEMA_NAME};

-- PostgreSQL refuses to alter a column a view depends on. Views are rebuilt from 060 on every upgrade.
DROP VIEW IF EXISTS v_latest_profile_results CASCADE;
DROP VIEW IF EXISTS v_inactive_anomalies CASCADE;
DROP VIEW IF EXISTS v_queued_observability_results CASCADE;
DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_column CASCADE;
DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_dimension CASCADE;
DROP VIEW IF EXISTS v_dq_profile_scoring_latest_by_impact_dimension CASCADE;
DROP VIEW IF EXISTS v_dq_profile_scoring_history_by_column CASCADE;
DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_column CASCADE;
DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_dimension CASCADE;
DROP VIEW IF EXISTS v_dq_test_scoring_latest_by_impact_dimension CASCADE;
DROP VIEW IF EXISTS v_dq_test_scoring_history_by_column CASCADE;

-- Struct, array and map type definitions run past 50 characters, and a single one fails the whole refresh
ALTER TABLE stg_data_chars_updates
    ALTER COLUMN column_type TYPE VARCHAR,
    ALTER COLUMN db_data_type TYPE VARCHAR,
    ADD COLUMN IF NOT EXISTS logical_type VARCHAR(20);

ALTER TABLE data_column_chars
    ALTER COLUMN column_type TYPE VARCHAR,
    ALTER COLUMN db_data_type TYPE VARCHAR,
    ADD COLUMN IF NOT EXISTS logical_type VARCHAR(20);

ALTER TABLE profile_results
    ALTER COLUMN column_type TYPE VARCHAR,
    ALTER COLUMN db_data_type TYPE VARCHAR;

ALTER TABLE profile_anomaly_results
    ALTER COLUMN column_type TYPE VARCHAR,
    ALTER COLUMN db_data_type TYPE VARCHAR;

ALTER TABLE data_structure_log
    ALTER COLUMN old_data_type TYPE VARCHAR,
    ALTER COLUMN new_data_type TYPE VARCHAR;

-- The catalog refresh spells these types the way the database declares them. Rewriting the stored
-- values the same way keeps the next refresh from logging every such column as modified.
-- A stored (6) is PostgreSQL's default precision, which the refresh leaves out when none was declared.
UPDATE data_column_chars dcc
   SET db_data_type = CASE
           WHEN dcc.db_data_type LIKE '%(6)'
               THEN REGEXP_REPLACE(dcc.db_data_type, '^(time|timestamp) (with(out)? time zone)\(6\)$', '\1 \2')
           ELSE REGEXP_REPLACE(dcc.db_data_type, '^(time|timestamp) (with(out)? time zone)\((\d+)\)$', '\1(\4) \2')
       END
  FROM table_groups tg
       INNER JOIN connections c ON (tg.connection_id = c.connection_id)
 WHERE dcc.table_groups_id = tg.id
   AND c.sql_flavor = 'postgresql'
   AND dcc.db_data_type ~ '^(time|timestamp) with(out)? time zone\(\d+\)$';

UPDATE data_column_chars dcc
   SET db_data_type = REPLACE(dcc.db_data_type, '(-1)', '(max)')
  FROM table_groups tg
       INNER JOIN connections c ON (tg.connection_id = c.connection_id)
 WHERE dcc.table_groups_id = tg.id
   AND c.sql_flavor = 'mssql'
   AND dcc.db_data_type LIKE '%(-1)';
