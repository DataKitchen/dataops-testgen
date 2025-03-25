import streamlit as st

import testgen.ui.queries.connection_queries as connection_queries
import testgen.ui.services.table_group_service as table_group_service
from testgen.commands.run_profiling_bridge import InitializeProfilingSQL
from testgen.common.database.database_service import (
    AssignConnectParms,
    empty_cache,
    get_db_type,
    get_flavor_service,
)
from testgen.common.encrypt import DecryptText, EncryptText


def get_by_id(connection_id: str, hide_passwords: bool = True) -> dict | None:
    connections_df = connection_queries.get_by_id(connection_id)
    decrypt_connections(connections_df, hide_passwords)
    connections_list = connections_df.to_dict(orient="records")
    if len(connections_list):
        return connections_list[0]


def get_connections(project_code, hide_passwords: bool = False):
    connections = connection_queries.get_connections(project_code)
    decrypt_connections(connections, hide_passwords)
    return connections


def decrypt_connections(connections, hide_passwords: bool = False):
    for index, connection in connections.iterrows():
        if hide_passwords:
            password = "***"  # noqa S105
            private_key = "***"  # S105
            private_key_passphrase = "***"  # noqa S105
        else:
            password = DecryptText(connection["project_pw_encrypted"]) if connection["project_pw_encrypted"] else None
            private_key = DecryptText(connection["private_key"]) if connection["private_key"] else None
            private_key_passphrase = DecryptText(connection["private_key_passphrase"]) if connection["private_key_passphrase"] else ""
        connections.at[index, "password"] = password
        connections.at[index, "private_key"] = private_key
        connections.at[index, "private_key_passphrase"] = private_key_passphrase


def encrypt_credentials(connection):
    encrypted_password = EncryptText(connection["password"]) if connection["password"] else None
    encrypted_private_key = EncryptText(connection["private_key"]) if connection["private_key"] else None
    encrypted_private_key_passphrase = EncryptText(connection["private_key_passphrase"]) if connection["private_key_passphrase"] else None
    return encrypted_password, encrypted_private_key, encrypted_private_key_passphrase


def edit_connection(connection):
    empty_cache()
    schema = st.session_state["dbschema"]
    connection = pre_save_connection_process(connection)
    encrypted_password, encrypted_private_key, encrypted_private_key_passphrase = encrypt_credentials(connection)
    connection_queries.edit_connection(schema, connection, encrypted_password, encrypted_private_key, encrypted_private_key_passphrase)


def add_connection(connection) -> int:
    empty_cache()
    schema = st.session_state["dbschema"]
    connection = pre_save_connection_process(connection)
    encrypted_password, encrypted_private_key, encrypted_private_key_passphrase = encrypt_credentials(connection)
    return connection_queries.add_connection(
        schema,
        connection,
        encrypted_password,
        encrypted_private_key,
        encrypted_private_key_passphrase,
    )


def pre_save_connection_process(connection):
    if connection["connect_by_url"]:
        url = connection["url"]
        if url:
            url_sections = url.split("/")
            if len(url_sections) > 0:
                host_port = url_sections[0]
                host_port_sections = host_port.split(":")
                if len(host_port_sections) > 0:
                    connection["project_host"] = host_port_sections[0]
                    connection["project_port"] = "".join(host_port_sections[1:])
                else:
                    connection["project_host"] = host_port
                    connection["project_port"] = ""
            if len(url_sections) > 1:
                connection["project_db"] = url_sections[1]
    return connection


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
    connect_by_key = connection["connect_by_key"]
    private_key = connection["private_key"]
    private_key_passphrase = connection["private_key_passphrase"]
    project_host = connection["project_host"]
    project_port = connection["project_port"]
    project_db = connection["project_db"]
    project_user = connection["project_user"]
    password = connection["password"]
    http_path = connection["http_path"]

    # prepare the profiling query
    clsProfiling = InitializeProfilingSQL(project_code, sql_flavor)

    AssignConnectParms(
        project_code,
        connection_id,
        project_host,
        project_port,
        project_db,
        table_group_schema,
        project_user,
        sql_flavor,
        url,
        connect_by_url,
        connect_by_key,
        private_key,
        private_key_passphrase,
        http_path,
        connectname="PROJECT",
        password=password,
    )

    return clsProfiling


def form_overwritten_connection_url(connection):
    flavor = connection["sql_flavor"]

    connection_credentials = {
        "flavor": flavor,
        "user": "<user>",
        "host": connection["project_host"],
        "port": connection["project_port"],
        "dbname": connection["project_db"],
        "url": None,
        "connect_by_url": None,
        "connect_by_key": connection.get("connect_by_key"),
        "private_key": None,
        "private_key_passphrase": "",
        "dbschema": "",
    }

    db_type = get_db_type(flavor)
    flavor_service = get_flavor_service(db_type)
    flavor_service.init(connection_credentials)
    connection_string = flavor_service.get_connection_string("<password>")

    return connection_string
