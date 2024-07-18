SELECT
	id,
	project_code as project_key,
	connection_id,
	connection_name,
	sql_flavor,
	project_host,
	project_port,
	project_user,
	project_db,
    project_pw_encrypted,
	max_threads,
	max_query_chars,
    project_qc_schema,
    url,
    connect_by_url,
    connect_by_key,
    private_key,
    private_key_passphrase
FROM connections
WHERE connection_id = {CONNECTION_ID};
