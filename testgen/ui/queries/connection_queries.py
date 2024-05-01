import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db


def get_by_id(connection_id):
    str_schema = st.session_state["dbschema"]
    str_sql = f"""
           SELECT id::VARCHAR(50), project_code, connection_id, connection_name,
                  sql_flavor, project_host, project_port, project_user, project_qc_schema,
                  project_db, project_pw_encrypted, NULL as password,
                  max_threads, max_query_chars, url, connect_by_url
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
                  max_threads, max_query_chars, connect_by_url, url
             FROM {str_schema}.connections
             WHERE project_code = '{project_code}'
           ORDER BY connection_id
    """
    return db.retrieve_data(str_sql)


def get_table_group_names_by_connection(schema: str, connection_ids: list[str]) -> pd.DataFrame:
    items = [f"'{item}'" for item in connection_ids]
    str_sql = f"""select table_groups_name from {schema}.table_groups where connection_id in ({",".join(items)})"""
    return db.retrieve_data(str_sql)


def edit_connection(schema, connection, encrypted_password):
    sql = f"""UPDATE  {schema}.connections SET
        project_code = '{connection["project_code"]}',
        sql_flavor = '{connection["sql_flavor"]}',
        project_host = '{connection["project_host"]}',
        project_port = '{connection["project_port"]}',
        project_user = '{connection["project_user"]}',
        project_db = '{connection["project_db"]}',
        project_qc_schema = '{connection["project_qc_schema"]}',
        connection_name = '{connection["connection_name"]}',
        project_pw_encrypted = '{encrypted_password}',
        max_threads = '{connection["max_threads"]}',
        max_query_chars = '{connection["max_query_chars"]}',
        url = '{connection["url"]}',
        connect_by_url = '{connection["connect_by_url"]}'
        WHERE
        connection_id = '{connection["connection_id"]}';"""
    db.execute_sql(sql)
    st.cache_data.clear()


def add_connection(schema, connection, encrypted_password):
    sql = f"""INSERT INTO {schema}.connections
        (project_code, sql_flavor, url, connect_by_url, project_host, project_port, project_user, project_db, project_qc_schema,
        connection_name, project_pw_encrypted, max_threads, max_query_chars)
    SELECT
        '{connection["project_code"]}' as project_code,
        '{connection["sql_flavor"]}' as sql_flavor,
        '{connection["url"]}' as url,
        '{connection["connect_by_url"]}' as connect_by_url,
        '{connection["project_host"]}' as project_host,
        '{connection["project_port"]}' as project_port,
        '{connection["project_user"]}' as project_user,
        '{connection["project_db"]}' as project_db,
        '{connection["project_qc_schema"]}' as project_qc_schema,
        '{connection["connection_name"]}' as connection_name,
        '{encrypted_password}' as project_pw_encrypted,
        '{connection["max_threads"]}' as max_threads,
        '{connection["max_query_chars"]}' as max_query_chars;"""
    db.execute_sql(sql)
    st.cache_data.clear()


def delete_connections(schema, connection_ids):
    if connection_ids is None or len(connection_ids) == 0:
        raise ValueError("No connection is specified.")

    items = [f"'{item}'" for item in connection_ids]
    sql = f"""DELETE FROM {schema}.connections WHERE connection_id in ({",".join(items)})"""
    db.execute_sql(sql)
    st.cache_data.clear()
