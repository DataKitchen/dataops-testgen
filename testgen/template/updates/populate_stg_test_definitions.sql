DROP TABLE IF EXISTS tmp_stg_test_definitions CASCADE;

CREATE TEMPORARY TABLE tmp_stg_test_definitions
(
    id                     uuid,
    cat_test_id            bigint,
    project_code           varchar(30),
    table_groups_id        uuid,
    profile_run_id         uuid,
    test_type              varchar(200),
    test_suite             varchar(200),
    test_description       varchar(1000),
    test_action            varchar(100),
    schema_name            varchar(100),
    table_name             varchar(100),
    column_name            varchar(500),
    skip_errors            integer,
    baseline_ct            varchar(1000),
    baseline_unique_ct     varchar(1000),
    baseline_value         varchar(1000),
    baseline_value_ct      varchar(1000),
    threshold_value        varchar(1000),
    baseline_sum           varchar(1000),
    baseline_avg           varchar(1000),
    baseline_sd            varchar(1000),
    subset_condition       varchar(500),
    groupby_names          varchar(200),
    having_condition       varchar(500),
    window_date_column     varchar(100),
    window_days            integer,
    match_schema_name      varchar(100),
    match_table_name       varchar(100),
    match_column_names     varchar(200),
    match_subset_condition varchar(500),
    match_groupby_names    varchar(200),
    match_having_condition varchar(500),
    test_mode              varchar(20),
    custom_query           varchar(4000),
    test_active            varchar(10),
    severity               varchar(10),
    watch_level            varchar(10),
    check_result           varchar(500),
    lock_refresh           varchar(10),
    last_auto_gen_date     timestamp,
    profiling_as_of_date   timestamp
);


INSERT INTO tmp_stg_test_definitions (project_code, test_suite, schema_name, table_name, column_name,
                                  id, test_type, test_description, test_action, test_active,lock_refresh, severity,
                                  baseline_ct,baseline_unique_ct,baseline_value,baseline_value_ct,threshold_value,
                                  baseline_sum,baseline_avg,baseline_sd,subset_condition,groupby_names,having_condition,
                                  window_date_column,window_days,match_schema_name,match_table_name,match_column_names,
                                  match_subset_condition,match_groupby_names, match_having_condition   )
SELECT project_code,
       test_suite,
       schema_name,
       table_name,
       column_name,
       id,
       test_type,
       test_description,
       test_action,
       CASE WHEN lower(test_active) = 'none' THEN 'N' ELSE test_active END as test_active,
       CASE WHEN lower(lock_refresh) = 'none' THEN 'N' ELSE lock_refresh END as lock_refresh,
       CASE WHEN lower(severity) IN ('warning','fail','ignore') THEN initcap(severity) ELSE NULL END as severity,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'baseline_ct'            )  AS baseline_ct,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'baseline_unique_ct'     )  AS baseline_unique_ct,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'baseline_value'         )  AS baseline_value,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'baseline_value_ct'      )  AS baseline_value_ct,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'threshold_value'        )  AS threshold_value,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'baseline_sum'           )  AS baseline_sum,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'baseline_avg'           )  AS baseline_avg,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'baseline_sd'            )  AS baseline_sd,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'subset_condition'       )  AS subset_condition,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'groupby_names'          )  AS groupby_names,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'having_condition'       )  AS having_condition,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'window_date_column'     )  AS window_date_column,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'window_days'            ) :: integer AS window_days,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'match_schema_name'      )  AS match_schema_name,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'match_table_name'       )  AS match_table_name,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'match_column_names'     )  AS match_column_names,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'match_subset_condition' )  AS match_subset_condition,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'match_groupby_names'    )  AS match_groupby_names,
        MAX(test_parameter_value) FILTER( WHERE test_parameter = 'match_having_condition' )  AS match_having_condition
FROM tmp_test_definition
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12
ORDER BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12;


--- UPDATE

UPDATE test_definitions
SET test_active            = CASE WHEN lower(c.test_active) = 'none' THEN 'N' ELSE c.test_active END,
    lock_refresh           = CASE WHEN lower(c.lock_refresh) = 'none' THEN 'N' ELSE c.lock_refresh END,
    severity               = CASE WHEN lower(c.severity) IN ('warning','fail','ignore') THEN initcap(c.severity) ELSE NULL END,
    last_manual_update     = current_timestamp       ,
    baseline_ct            = c.baseline_ct           ,
    baseline_unique_ct     = c.baseline_unique_ct    ,
    baseline_value         = c.baseline_value        ,
    baseline_value_ct      = c.baseline_value_ct     ,
    threshold_value        = c.threshold_value       ,
    baseline_sum           = c.baseline_sum          ,
    baseline_avg           = c.baseline_avg          ,
    baseline_sd            = c.baseline_sd           ,
    subset_condition       = c.subset_condition      ,
    groupby_names          = c.groupby_names         ,
    having_condition       = c.having_condition      ,
    window_date_column     = c.window_date_column    ,
    window_days            = c.window_days           ,
    match_schema_name      = c.match_schema_name     ,
    match_table_name       = c.match_table_name      ,
    match_column_names     = c.match_column_names    ,
    match_subset_condition = c.match_subset_condition,
    match_groupby_names    = c.match_groupby_names
    FROM ( SELECT b.* FROM tmp_stg_test_definitions b
       LEFT JOIN test_definitions a
       ON a.project_code = b.project_code
           AND a.test_suite    = b.test_suite
           AND a.schema_name   = b.schema_name
           AND a.table_name    = b.table_name
           AND a.column_name   = b.column_name
           AND a.test_type     = b.test_type
       WHERE (a.test_active != b.test_active)
          OR (a.lock_refresh != b.lock_refresh)
          OR (coalesce(a.severity,'') != coalesce(b.severity,''))
          OR (a.baseline_ct            != b.baseline_ct           )
          OR (a.baseline_unique_ct     != b.baseline_unique_ct    )
          OR (a.baseline_value         != b.baseline_value        )
          OR (a.baseline_value_ct      != b.baseline_value_ct     )
          OR (a.threshold_value        != b.threshold_value       )
          OR (a.baseline_sum           != b.baseline_sum          )
          OR (a.baseline_avg           != b.baseline_avg          )
          OR (a.baseline_sd            != b.baseline_sd           )
          OR (a.subset_condition       != b.subset_condition      )
          OR (a.groupby_names          != b.groupby_names         )
          OR (a.having_condition       != b.having_condition      )
          OR (a.window_date_column     != b.window_date_column    )
          OR (a.window_days            != b.window_days           )
          OR (a.match_schema_name      != b.match_schema_name     )
          OR (a.match_table_name       != b.match_table_name      )
          OR (a.match_column_names     != b.match_column_names    )
          OR (a.match_subset_condition != b.match_subset_condition)
          OR (a.match_groupby_names    != b.match_groupby_names   )
       ) c
WHERE test_definitions.project_code  = c.project_code
  AND test_definitions.test_suite    = c.test_suite
  AND test_definitions.schema_name   = c.schema_name
  AND test_definitions.table_name    = c.table_name
  AND test_definitions.column_name   = c.column_name
  AND test_definitions.test_type     = c.test_type  ;


-- INSERT
INSERT INTO test_definitions (project_code, test_suite, schema_name, table_name, column_name,
                                  test_type, test_action, test_active, lock_refresh, severity, last_manual_update,
                                  baseline_ct,baseline_unique_ct,baseline_value,baseline_value_ct,threshold_value,
                                  baseline_sum,baseline_avg,baseline_sd,subset_condition,groupby_names,having_condition,
                                  window_date_column,window_days,match_schema_name,match_table_name,match_column_names,
                                  match_subset_condition,match_groupby_names, match_having_condition   )
SELECT a.project_code, a.test_suite, a.schema_name, a.table_name, a.column_name,
       a.test_type,
       CASE WHEN lower(a.test_action) = 'none' THEN NULL ELSE a.test_action END as test_action,
       CASE WHEN lower(a.test_active) = 'none' THEN 'N' ELSE a.test_active END as test_active,
       CASE WHEN lower(a.lock_refresh) = 'none' THEN 'N' ELSE a.lock_refresh END as lock_refresh,
       CASE WHEN lower(a.severity) IN ('warning','fail','ignore') THEN initcap(a.severity) ELSE NULL END as severity,
       current_timestamp  as last_manual_update,
       a.baseline_ct,a.baseline_unique_ct,a.baseline_value,a.baseline_value_ct,a.threshold_value,
       a.baseline_sum,a.baseline_avg,a.baseline_sd,a.subset_condition,a.groupby_names,a.having_condition,
       a.window_date_column,a.window_days,a.match_schema_name,a.match_table_name,a.match_column_names,
       a.match_subset_condition,a.match_groupby_names, a.match_having_condition
FROM tmp_stg_test_definitions a
         LEFT JOIN test_definitions b
                   ON a.project_code = b.project_code
                       AND a.test_suite    = b.test_suite
                       AND a.schema_name   = b.schema_name
                       AND a.table_name    = b.table_name
                       AND a.column_name   = b.column_name
                       AND a.test_type     = b.test_type
WHERE a.id IS NULL AND b.id is NULL;

DROP TABLE tmp_test_definition CASCADE;

DROP TABLE tmp_stg_test_definitions CASCADE;
