SELECT tg.project_code,
       tg.id::VARCHAR(50) as table_groups_id,
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
       tg.profile_pair_rule_pct
  FROM table_groups tg
 WHERE tg.id = :TABLE_GROUP_ID;
