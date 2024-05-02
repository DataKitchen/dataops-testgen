import streamlit as st

import testgen.ui.queries.connection_queries as connection_queries
import testgen.ui.services.table_group_service as table_group_service
from testgen.commands.run_profiling_bridge import InitializeProfilingSQL
from testgen.commands.run_setup_profiling_tools import run_setup_profiling_tools
from testgen.common.database.database_service import (
    AssignConnectParms,
    RetrieveDBResultsToList,
    empty_cache,
    get_db_type,
    get_flavor_service,
)
from testgen.common.encrypt import DecryptText, EncryptText


def get_by_id(connection_id, hide_passwords: bool = True):
    connections_df = connection_queries.get_by_id(connection_id)
    connection = connections_df.to_dict(orient="records")[0]

    if hide_passwords:
        connection["password"] = "***"  # noqa S105
    else:
        encrypted_password = connection["project_pw_encrypted"]
        password = DecryptText(encrypted_password)
        connection["password"] = password

    return connection


def get_connections(project_code, hide_passwords: bool = False):
    connections = connection_queries.get_connections(project_code)
    for index, connection in connections.iterrows():
        if hide_passwords:
            password = "***"  # noqa S105
        else:
            encrypted_password = connection["project_pw_encrypted"]
            password = DecryptText(encrypted_password)
            connection["password"] = password
        connections.at[index, "password"] = password
    return connections


def edit_connection(connection):
    empty_cache()
    encrypted_password = EncryptText(connection["password"])
    schema = st.session_state["dbschema"]
    connection_queries.edit_connection(schema, connection, encrypted_password)


def add_connection(connection):
    empty_cache()
    encrypted_password = EncryptText(connection["password"])
    schema = st.session_state["dbschema"]
    connection_queries.add_connection(schema, connection, encrypted_password)


def delete_connections(connection_ids):
    empty_cache()
    schema = st.session_state["dbschema"]
    return connection_queries.delete_connections(schema, connection_ids)


def cascade_delete(connection_ids, dry_run=False):
    schema = st.session_state["dbschema"]
    can_be_deleted = True
    table_group_names = get_table_group_names_by_connection(connection_ids)
    connection_has_dependencies = table_group_names is not None and len(table_group_names) > 0
    if connection_has_dependencies:
        can_be_deleted = False
    if not dry_run:
        if connection_has_dependencies:
            table_group_service.cascade_delete(table_group_names)
        connection_queries.delete_connections(schema, connection_ids)
    return can_be_deleted


def are_connections_in_use(connection_ids):
    table_group_names = get_table_group_names_by_connection(connection_ids)
    table_groups_in_use = table_group_service.are_table_groups_in_use(table_group_names)
    return table_groups_in_use


def get_table_group_names_by_connection(connection_ids):
    if not connection_ids:
        return []
    schema = st.session_state["dbschema"]
    table_group_names = connection_queries.get_table_group_names_by_connection(schema, connection_ids)
    return table_group_names.to_dict()["table_groups_name"].values()


def init_profiling_sql(project_code, connection, table_group_schema=None):
    # get connection data
    empty_cache()
    connection_id = str(connection["connection_id"]) if connection["connection_id"] else None
    sql_flavor = connection["sql_flavor"]
    url = connection["url"]
    connect_by_url = connection["connect_by_url"]
    project_host = connection["project_host"]
    project_port = connection["project_port"]
    project_db = connection["project_db"]
    project_user = connection["project_user"]
    project_qc_schema = connection["project_qc_schema"]
    password = connection["password"]

    # prepare the profiling query
    clsProfiling = InitializeProfilingSQL(project_code, sql_flavor)

    AssignConnectParms(
        project_code,
        connection_id,
        project_host,
        project_port,
        project_db,
        table_group_schema if table_group_schema else project_qc_schema,
        project_user,
        sql_flavor,
        url,
        connect_by_url,
        connectname="PROJECT",
        password=password,
    )

    return clsProfiling


def test_qc_connection(project_code, connection, init_profiling=True):
    qc_results = {}

    if init_profiling:
        init_profiling_sql(project_code, connection)

    project_qc_schema = connection["project_qc_schema"]
    query_isnum_true = f"select {project_qc_schema}.fndk_isnum('32')"
    query_isnum_true_result_raw = RetrieveDBResultsToList("PROJECT", query_isnum_true)
    isnum_true_result = query_isnum_true_result_raw[0][0][0] == 1
    qc_results["isnum_true_result"] = isnum_true_result

    query_isnum_false = f"select {project_qc_schema}.fndk_isnum('HELLO')"
    query_isnum_false_result_raw = RetrieveDBResultsToList("PROJECT", query_isnum_false)
    isnum_false_result = query_isnum_false_result_raw[0][0][0] == 0
    qc_results["isnum_false_result"] = isnum_false_result

    query_isdate_true = f"select {project_qc_schema}.fndk_isdate('2013-05-18')"
    query_isdate_true_result_raw = RetrieveDBResultsToList("PROJECT", query_isdate_true)
    isdate_true_result = query_isdate_true_result_raw[0][0][0] == 1
    qc_results["isdate_true_result"] = isdate_true_result

    query_isdate_false = f"select {project_qc_schema}.fndk_isdate('HELLO')"
    query_isdate_false_result_raw = RetrieveDBResultsToList("PROJECT", query_isdate_false)
    isdate_false_result = query_isdate_false_result_raw[0][0][0] == 0
    qc_results["isdate_false_result"] = isdate_false_result

    return qc_results


def create_qc_schema(connection_id, create_qc_schema, db_user, db_password, skip_granting_privileges):
    dry_run = False
    empty_cache()
    run_setup_profiling_tools(connection_id, dry_run, create_qc_schema, db_user, db_password, skip_granting_privileges)


def form_overwritten_connection_url(connection):
    flavor = connection["sql_flavor"]

    connection_credentials = {
        "flavor": flavor,
        "user": "<user>",
        "host": connection["project_host"],
        "port": connection["project_port"],
        "dbname": connection["project_db"],
        "url": None,
        "connect_by_url": False,
        "dbschema": "",
    }

    db_type = get_db_type(flavor)
    flavor_service = get_flavor_service(db_type)
    connection_string = flavor_service.get_connection_string(connection_credentials, "<password>")

    return connection_string
