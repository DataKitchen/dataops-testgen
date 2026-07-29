-- Classifies each table profiled by this run, using the table's profiling history to decide
-- whether its record count is cumulative or windowed.
--
-- The current run's tables come from profile_run_id, not from run_date: run_date is a label a
-- run stamps on its rows, and matching on it silently missed rows a run wrote under a
-- different value. The history scan is scoped by table_groups_id rather than
-- (project_code, schema_name), which mixed two table groups of one project pointing at the
-- same schema.
WITH tablesrank AS
         (SELECT DISTINCT p.project_code,
                          p.schema_name,
                          p.table_name,
                          p.run_date,
                          p.record_ct,
                          p.functional_data_type
          FROM profile_results p
         INNER JOIN (SELECT DISTINCT schema_name, table_name
                       FROM profile_results
                      WHERE profile_run_id = :PROFILE_RUN_ID) pt
                 ON (p.schema_name = pt.schema_name
                AND  p.table_name = pt.table_name)
          WHERE p.table_groups_id = :TABLE_GROUPS_ID
          ORDER BY p.schema_name, p.table_name, p.run_date DESC),
     tablescount AS
         (SELECT *
               , LAG(record_ct, 1)
                 OVER (PARTITION BY schema_name, table_name ORDER BY schema_name, table_name, run_date) AS prev_record_ct
               , LAG(run_date, 1)
                 OVER (PARTITION BY schema_name, table_name ORDER BY schema_name, table_name, run_date) AS prev_run_date
          FROM tablesrank
         ),
     tablestat AS
         (SELECT project_code,
                 schema_name,
                 table_name,
                 CASE
                 -- table period is cumulative is the current record count is always greater than the previous record count
                     WHEN SUM(CASE WHEN record_ct - prev_record_ct < 0 THEN 1 ELSE 0 END) = 0 THEN 'cumulative'
                     ELSE 'window' END AS table_period,
                 CASE
                     WHEN COUNT(CASE
                                WHEN functional_data_type ILIKE 'ID%'
                                  OR functional_data_type = 'Category' THEN 1 END) > 0
                      AND (
                            (COUNT(CASE WHEN functional_data_type ILIKE 'Period%' THEN 1 END) > 0
                              AND COUNT(CASE WHEN functional_data_type ILIKE 'Measure%' THEN 1 END) > 0)
                           OR COUNT(CASE WHEN functional_data_type ILIKE 'Measure%' THEN 1 END)::FLOAT
                                 /COUNT(CASE WHEN functional_data_type <> 'Constant' THEN 1 END)::FLOAT > 0.4
                         )  THEN 'summary'
                     WHEN COUNT(CASE WHEN functional_data_type ILIKE 'Measure%' THEN 1 END) > 0
                         AND COUNT(CASE WHEN functional_data_type ILIKE '%Transactional Date%' THEN 1 END) > 0
                         THEN 'transaction'
                     WHEN COUNT(CASE WHEN functional_data_type IN ('Entity Name', 'Person Last Name', 'Person Given Name', 'Person Full Name') THEN 1 END) > 0
                          AND COUNT(CASE WHEN functional_data_type IN ('Address', 'City', 'State') THEN 1 END) > 1
                          THEN 'entity'
                     WHEN COUNT(CASE WHEN functional_data_type IN ('ID-Unique', 'ID-Unique-SK', 'ID-Secondary') THEN 1 END) > 1
                      AND COUNT(CASE WHEN functional_data_type IN ('Attribute', 'Description') THEN 1 END) <= 1
                      AND COUNT(CASE WHEN functional_data_type ILIKE 'Measure%' THEN 1 END) <= 1
                          THEN 'bridge'
                     ELSE 'domain' END AS table_type
          FROM tablescount
          GROUP BY project_code, schema_name, table_name
          ORDER BY project_code, schema_name, table_name)
INSERT INTO stg_functional_table_updates
(project_code, schema_name, run_date, table_name, table_period, table_type)
SELECT project_code, schema_name, :RUN_DATE as run_date,
       table_name, table_period, table_type
FROM tablestat;
