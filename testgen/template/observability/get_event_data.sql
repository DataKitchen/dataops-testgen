Select
	   c.sql_flavor as sql_flavor,
	   COALESCE(ts.component_key, tg.id::VARCHAR) as dataset_key,
	   COALESCE(ts.component_name, tg.table_groups_name) as dataset_name,
	   tg.table_group_schema as schema,
	   c.connection_name as connection_name,
	   c.project_db as project_db,
	   tg.profile_sample_min_count as profile_sample_minimum_count,
	   ts.table_groups_id as table_groups_id,
	   tg.profile_use_sampling as profile_use_sampling,
	   tg.profile_sample_percent as profile_sample_percent,
	   pr.project_code as project_code,
	   tg.profiling_table_set as profiling_table_set,
	   tg.profiling_include_mask as profiling_include_mask,
	   tg.profiling_exclude_mask as profiling_exclude_mask,
       pr.observability_api_key as observability_api_key,
       pr.observability_api_url as observability_api_url
from test_suites ts
join connections c on c.connection_id = ts.connection_id
join projects pr on pr.project_code = ts.project_code
join table_groups tg on tg.id = ts.table_groups_id
where ts.id = '{TEST_SUITE_ID}'
