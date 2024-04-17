SELECT
	id,
	project_code as project_key,
	connection_id,
	sql_flavor,
	project_host,
	max_threads,
	max_query_chars
FROM connections;
