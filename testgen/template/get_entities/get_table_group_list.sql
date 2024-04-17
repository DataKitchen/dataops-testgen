SELECT
    id as table_group_id,
    project_code as project_key,
    connection_id,
    table_group_schema,
    profiling_table_set,
    profiling_include_mask as include_mask,
    profiling_exclude_mask as exclude_mask
FROM table_groups
where project_code = '{PROJECT_CODE}';
