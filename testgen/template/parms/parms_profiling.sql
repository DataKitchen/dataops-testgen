SELECT tg.project_code,
       tg.id::VARCHAR(50) as table_groups_id,
       tg.table_group_schema,
       tg.table_group_schema,
       CASE
         WHEN tg.profiling_table_set ILIKE '''%''' THEN tg.profiling_table_set
         ELSE fn_format_csv_quotes(tg.profiling_table_set)
       END as profiling_table_set,
       tg.profiling_include_mask,
       tg.profiling_exclude_mask,
       tg.profile_id_column_mask,
       tg.profile_sk_column_mask,
       tg.profile_use_sampling,
       tg.profile_flag_cdes,
       tg.profile_sample_percent,
       tg.profile_sample_min_count,
       tg.profile_do_pair_rules,
       tg.profile_pair_rule_pct,
       CASE
        WHEN tg.monitor_test_suite_id IS NULL THEN NULL
        ELSE tg.monitor_test_suite_id::VARCHAR(50)
       END as monitor_test_suite_id,
       CASE
        WHEN tg.last_complete_profile_run_id is NULL THEN NULL
        ELSE tg.last_complete_profile_run_id::VARCHAR(50)
       END as last_complete_profile_run_id
  FROM table_groups tg
 WHERE tg.id = :TABLE_GROUP_ID;
