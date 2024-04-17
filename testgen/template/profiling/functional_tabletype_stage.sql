WITH tablesrank AS
         (SELECT DISTINCT p.project_code,
                          p.schema_name,
                          p.table_name,
                          p.run_date,
                          p.record_ct,
                          p.functional_data_type,
                          DENSE_RANK() OVER (PARTITION BY p.schema_name, p.table_name ORDER BY p.run_date DESC) AS rnk
          FROM profile_results p
         INNER JOIN (SELECT DISTINCT schema_name, table_name
                       FROM profile_results
                      WHERE project_code = '{PROJECT_CODE}'
                        AND schema_name = '{DATA_SCHEMA}'
                        AND run_date = '{RUN_DATE}') pt
                 ON (p.schema_name = pt.schema_name
                AND  p.table_name = pt.table_name)
          WHERE p.project_code = '{PROJECT_CODE}'
            AND p.schema_name = '{DATA_SCHEMA}'
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
                     WHEN SUM(CASE WHEN functional_data_type = 'Measurement' THEN 1 ELSE 0 END) > 0
                         AND SUM(CASE WHEN functional_data_type ILIKE '%Transactional Date%' THEN 1 ELSE 0 END) > 0
                         THEN 'transaction'
                     ELSE 'domain' END AS table_type
          FROM tablescount
          GROUP BY project_code, schema_name, table_name
          ORDER BY project_code, schema_name, table_name)
INSERT INTO stg_functional_table_updates
(project_code, schema_name, run_date, table_name, table_period, table_type)
SELECT project_code, schema_name, '{RUN_DATE}' as run_date,
       table_name, table_period, table_type
FROM tablestat;
