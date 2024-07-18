SELECT cc.project_code,
       cc.connection_id::VARCHAR(50) as connection_id,
       cc.sql_flavor,
       cc.url,
       cc.connect_by_url,
       cc.connect_by_key,
       cc.private_key,
       cc.private_key_passphrase,
       cc.project_host,
       cc.project_port,
       cc.project_user,
       cc.project_db,
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
       tg.profile_sample_percent,
       tg.profile_sample_min_count,
       cc.project_qc_schema,
       tg.profile_do_pair_rules,
       tg.profile_pair_rule_pct,
       cc.max_threads
  FROM table_groups tg
  INNER JOIN connections cc
         on cc.project_code = tg.project_code
        and cc.connection_id = tg.connection_id
 WHERE tg.id = '{TABLE_GROUPS_ID}'::UUID;
