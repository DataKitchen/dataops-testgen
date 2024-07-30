import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db


def get_by_id(connection_id):
    str_schema = st.session_state["dbschema"]
    str_sql = f"""
           SELECT id::VARCHAR(50), project_code, connection_id, connection_name,
                  sql_flavor, project_host, project_port, project_user, project_qc_schema,
                  project_db, project_pw_encrypted, NULL as password,
                  max_threads, max_query_chars, url, connect_by_url, connect_by_key, private_key, private_key_passphrase
             FROM {str_schema}.connections
             WHERE connection_id = '{connection_id}'
    """
    return db.retrieve_data(str_sql)


def get_connections(project_code):
    str_schema = st.session_state["dbschema"]
    str_sql = f"""
           SELECT id::VARCHAR(50), project_code, connection_id, connection_name,
                  sql_flavor, project_host, project_port, project_user, project_qc_schema,
                  project_db, project_pw_encrypted, NULL as password,
                  max_threads, max_query_chars, connect_by_url, url, connect_by_key, private_key,
                  private_key_passphrase
             FROM {str_schema}.connections
             WHERE project_code = '{project_code}'
           ORDER BY connection_id
    """
    return db.retrieve_data(str_sql)


def get_table_group_names_by_connection(schema: str, connection_ids: list[str]) -> pd.DataFrame:
    items = [f"'{item}'" for item in connection_ids]
    str_sql = f"""select table_groups_name from {schema}.table_groups where connection_id in ({",".join(items)})"""
    return db.retrieve_data(str_sql)


def edit_connection(schema, connection, encrypted_password, encrypted_private_key, encrypted_private_key_passphrase):
    sql = f"""UPDATE  {schema}.connections SET
        project_code = '{connection["project_code"]}',
        sql_flavor = '{connection["sql_flavor"]}',
        project_host = '{connection["project_host"]}',
        project_port = '{connection["project_port"]}',
        project_user = '{connection["project_user"]}',
        project_db = '{connection["project_db"]}',
        project_qc_schema = '{connection["project_qc_schema"]}',
        connection_name = '{connection["connection_name"]}',
        max_threads = '{connection["max_threads"]}',
        max_query_chars = '{connection["max_query_chars"]}',
        url = '{connection["url"]}',
        connect_by_key = '{connection["connect_by_key"]}',
        connect_by_url = '{connection["connect_by_url"]}'"""

    if encrypted_password:
        sql += f""", project_pw_encrypted = '{encrypted_password}' """

    if encrypted_private_key:
        sql += f""", private_key = '{encrypted_private_key}' """

    if encrypted_private_key_passphrase:
        sql += f""", private_key_passphrase = '{encrypted_private_key_passphrase}' """

    sql += f""" WHERE connection_id = '{connection["connection_id"]}';"""
    db.execute_sql(sql)
    st.cache_data.clear()


def add_connection(schema, connection, encrypted_password, encrypted_private_key, encrypted_private_key_passphrase):

    sql_header = f"""INSERT INTO {schema}.connections
        (project_code, sql_flavor, url, connect_by_url, connect_by_key,  
        project_host, project_port, project_user, project_db, project_qc_schema,
        connection_name,"""

    sql_footer = f""" SELECT
        '{connection["project_code"]}' as project_code,
        '{connection["sql_flavor"]}' as sql_flavor,
        '{connection["url"]}' as url,
        {connection["connect_by_url"]} as connect_by_url,
        {connection["connect_by_key"]} as connect_by_key,
        '{connection["project_host"]}' as project_host,
        '{connection["project_port"]}' as project_port,
        '{connection["project_user"]}' as project_user,
        '{connection["project_db"]}' as project_db,
        '{connection["project_qc_schema"]}' as project_qc_schema,
        '{connection["connection_name"]}' as connection_name, """

    if encrypted_password:
        sql_header += "project_pw_encrypted, "
        sql_footer += f""" '{encrypted_password}' as project_pw_encrypted, """

    if encrypted_private_key:
        sql_header += "private_key, "
        sql_footer += f""" '{encrypted_private_key}' as private_key, """

    if encrypted_private_key_passphrase:
        sql_header += "private_key_passphrase, "
        sql_footer += f""" '{encrypted_private_key_passphrase}' as private_key_passphrase, """

    sql_header += """max_threads, max_query_chars) """

    sql_footer += f""" '{connection["max_threads"]}' as max_threads,
        '{connection["max_query_chars"]}' as max_query_chars;"""

    sql = sql_header + sql_footer

    db.execute_sql(sql)
    st.cache_data.clear()


def delete_connections(schema, connection_ids):
    if connection_ids is None or len(connection_ids) == 0:
        raise ValueError("No connection is specified.")

    items = [f"'{item}'" for item in connection_ids]
    sql = f"""DELETE FROM {schema}.connections WHERE connection_id in ({",".join(items)})"""
    db.execute_sql(sql)
    st.cache_data.clear()
