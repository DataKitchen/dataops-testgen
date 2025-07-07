import base64
import logging
import typing
from dataclasses import asdict, dataclass, field

import streamlit as st

try:
    from pyodbc import Error as PyODBCError
except ImportError:
    PyODBCError = None
from sqlalchemy.exc import DatabaseError, DBAPIError

import testgen.ui.services.database_service as db
from testgen.commands.run_profiling_bridge import run_profiling_in_background
from testgen.common.database.database_service import empty_cache
from testgen.common.models import with_database_session
from testgen.ui.assets import get_asset_data_url
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import connection_service, table_group_service, user_session_service
from testgen.ui.session import session, temp_value
from testgen.utils import format_field

LOG = logging.getLogger("testgen")
PAGE_TITLE = "Connection"
CLEAR_SENTINEL = "<clear>"


class ConnectionsPage(Page):
    path = "connections"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon="database",
        label=PAGE_TITLE,
        section="Data Configuration",
        order=1,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
    )

    def render(self, project_code: str, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "connect-your-database",
        )

        dataframe = connection_service.get_connections(project_code)
        connection = dataframe.iloc[0]
        has_table_groups = (
            len(connection_service.get_table_group_names_by_connection([connection["connection_id"]]) or []) > 0
        )
        user_is_admin = user_session_service.user_is_admin()
        should_check_status, set_check_status = temp_value(
            "connections:status_check",
            default=False,
        )
        get_updated_connection, set_updated_connection = temp_value(
            "connections:partial_value",
            default={},
        )
        should_save, set_save = temp_value(
            "connections:update_connection",
            default=False,
        )

        def on_save_connection_clicked(updated_connection):
            is_pristine = lambda value: value in ["", "***"]

            if updated_connection.get("connect_by_url", False):
                url_parts = updated_connection.get("url", "").split("@")
                if len(url_parts) > 1:
                    updated_connection["url"] = url_parts[1]

            if updated_connection.get("connect_by_key"):
                updated_connection["password"] = ""
                if is_pristine(updated_connection["private_key_passphrase"]):
                    del updated_connection["private_key_passphrase"]
            else:
                updated_connection["private_key"] = ""
                updated_connection["private_key_passphrase"] = ""

            if updated_connection.get("private_key_passphrase") == CLEAR_SENTINEL:
                updated_connection["private_key_passphrase"] = ""

            if is_pristine(updated_connection.get("private_key")):
                del updated_connection["private_key"]
            else:
                updated_connection["private_key"] = base64.b64decode(updated_connection["private_key"]).decode()

            updated_connection["sql_flavor"] = self._get_sql_flavor_from_value(updated_connection["sql_flavor_code"]).flavor

            set_save(True)
            set_updated_connection(updated_connection)

        def on_test_connection_clicked(updated_connection: dict) -> None:
            password = updated_connection.get("password")
            private_key = updated_connection.get("private_key")
            private_key_passphrase = updated_connection.get("private_key_passphrase")
            is_pristine = lambda value: value in ["", "***"]

            if is_pristine(password):
                del updated_connection["password"]

            if is_pristine(private_key):
                del updated_connection["private_key"]
            else:
                updated_connection["private_key"] = base64.b64decode(updated_connection["private_key"]).decode()

            if is_pristine(private_key_passphrase):
                del updated_connection["private_key_passphrase"]
            elif updated_connection.get("private_key_passphrase") == CLEAR_SENTINEL:
                updated_connection["private_key_passphrase"] = ""

            updated_connection["sql_flavor"] = self._get_sql_flavor_from_value(updated_connection["sql_flavor_code"]).flavor

            set_check_status(True)
            set_updated_connection(updated_connection)

        results = None
        connection = {**connection.to_dict(), **get_updated_connection()}
        if should_save():
            success = True
            try:
                connection_service.edit_connection(connection)
                message = "Changes have been saved successfully."
            except Exception as error:
                message = "Error creating connection"
                success = False
                LOG.exception(message)
            
            results = {
                "success": success,
                "message": message,
            }

        return testgen.testgen_component(
            "connections",
            props={
                "project_code": project_code,
                "connection": self._format_connection(connection, should_test=should_check_status()),
                "has_table_groups": has_table_groups,
                "flavors": [asdict(flavor) for flavor in FLAVOR_OPTIONS],
                "permissions": {
                    "is_admin": user_is_admin,
                },
                "results": results,
            },
            on_change_handlers={
                "TestConnectionClicked": on_test_connection_clicked,
                "SaveConnectionClicked": on_save_connection_clicked,
                "SetupTableGroupClicked": lambda _: self.setup_data_configuration(project_code, connection["connection_id"]),
            },
        )

    def _get_sql_flavor_from_value(self, value: str) -> "ConnectionFlavor | None":
        match = [f for f in FLAVOR_OPTIONS if f.value == value]
        if match:
            return match[0]
        return None

    def _format_connection(self, connection: dict, should_test: bool = False) -> dict:
        formatted_connection = format_connection(connection)
        if should_test:
            formatted_connection["status"] = asdict(self.test_connection(connection))
        return formatted_connection

    def test_connection(self, connection: dict) -> "ConnectionStatus":
        empty_cache()
        try:
            sql_query = "select 1;"
            results = db.retrieve_target_db_data(
                connection["sql_flavor"],
                connection["project_host"],
                connection["project_port"],
                connection["project_db"],
                connection["project_user"],
                connection["password"],
                connection["url"],
                connection["connect_by_url"],
                connection["connect_by_key"],
                connection.get("private_key", ""),
                connection.get("private_key_passphrase", ""),
                connection.get("http_path", ""),
                sql_query,
            )
            connection_successful = len(results) == 1 and results[0][0] == 1

            if not connection_successful:
                return ConnectionStatus(message="Error completing a query to the database server.", successful=False)
            return ConnectionStatus(message="The connection was successful.", successful=True)
        except KeyError:
            return ConnectionStatus(
                message="Error attempting the connection. ",
                details="Complete all the required fields.",
                successful=False,
            )
        except DatabaseError as error:
            LOG.exception("Error testing database connection")
            return ConnectionStatus(message="Error attempting the connection.", details=str(error.orig), successful=False)
        except DBAPIError as error:
            LOG.exception("Error testing database connection")
            details = str(error.orig)
            if PyODBCError and isinstance(error.orig, PyODBCError) and error.orig.args:
                details = error.orig.args[1]
            return ConnectionStatus(message="Error attempting the connection.", details=details, successful=False)
        except (TypeError, ValueError) as error:
            LOG.exception("Error testing database connection")
            details = str(error)
            if is_open_ssl_error(error):
                details = error.args[0]
            return ConnectionStatus(message="Error attempting the connection.", details=details, successful=False)
        except Exception as error:
            details = "Try again"
            if connection["connect_by_key"] and not connection.get("private_key", ""):
                details = "The private key is missing."
            LOG.exception("Error testing database connection")
            return ConnectionStatus(message="Error attempting the connection.", details=details, successful=False)

    @st.dialog(title="Data Configuration Setup")
    @with_database_session
    def setup_data_configuration(self, project_code: str, connection_id: str) -> None:
        def on_save_table_group_clicked(payload: dict) -> None:
            table_group: dict = payload["table_group"]
            run_profiling: bool = payload.get("run_profiling", False)

            set_new_table_group(table_group)
            set_run_profiling(run_profiling)

        def on_go_to_profiling_runs(params: dict) -> None:
            set_navigation_params({ **params, "project_code": project_code })

        get_navigation_params, set_navigation_params = temp_value(
            "connections:new_table_group:go_to_profiling_run",
            default=None,
        )
        if (params := get_navigation_params()):
            self.router.navigate(to="profiling-runs", with_args=params)

        get_new_table_group, set_new_table_group = temp_value(
            "connections:new_connection:table_group",
            default={},
        )
        get_run_profiling, set_run_profiling = temp_value(
            "connections:new_connection:run_profiling",
            default=False,
        )

        results = None
        table_group = get_new_table_group()
        should_run_profiling = get_run_profiling()
        if table_group:
            success = True
            message = None
            table_group_id = None

            try:
                table_group_id = table_group_service.add({
                    **table_group,
                    "project_code": project_code,
                    "connection_id": connection_id,
                })

                if should_run_profiling:
                    try:
                        run_profiling_in_background(table_group_id)
                        message = f"Profiling run started for table group {table_group['table_groups_name']}."
                    except Exception as error:
                        message = "Profiling run encountered errors"
                        success = False
                        LOG.exception(message)
                else:
                    LOG.info("Table group %s created", table_group_id)
                    st.rerun()
            except Exception as error:
                message = "Error creating table group"
                success = False
                LOG.exception(message)

            results = {
                "success": success,
                "message": message,
                "table_group_id": table_group_id,
            }

        testgen.testgen_component(
            "table_group_wizard",
            props={
                "project_code": project_code,
                "connection_id": connection_id,
                "results": results,
            },
            on_change_handlers={
                "SaveTableGroupClicked": on_save_table_group_clicked,
                "GoToProfilingRunsClicked": on_go_to_profiling_runs,
            },
        )


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    message: str
    successful: bool
    details: str | None = field(default=None)


def is_open_ssl_error(error: Exception):
    return (
        error.args
        and len(error.args) > 1
        and isinstance(error.args[1], list)
        and len(error.args[1]) > 0
        and type(error.args[1][0]).__name__ == "OpenSSLError"
    )


def format_connection(connection: dict) -> dict:
    fields = [
        "project_code",
        "connection_id",
        "connection_name",
        "sql_flavor",
        "sql_flavor_code",
        "project_host",
        "project_port",
        "project_db",
        "project_user",
        "password",
        "max_threads",
        "max_query_chars",
        "connect_by_url",
        "connect_by_key",
        "private_key",
        "private_key_passphrase",
        "http_path",
        "url",
    ]
    formatted_connection = {}

    for fieldname in fields:
        formatted_connection[fieldname] = format_field(connection[fieldname])

    if formatted_connection["password"]:
        formatted_connection["password"] = "***"  # noqa S105
    if formatted_connection["private_key"]:
        formatted_connection["private_key"] = "***"  # S105
    if formatted_connection["private_key_passphrase"]:
        formatted_connection["private_key_passphrase"] = "***"  # noqa S105

    flavors = [f for f in FLAVOR_OPTIONS if f.value == formatted_connection["sql_flavor_code"]]
    if flavors and (flavor := flavors[0]):
        formatted_connection["flavor"] = asdict(flavor)

    return formatted_connection


@dataclass(frozen=True, slots=True, kw_only=True)
class ConnectionFlavor:
    value: str
    label: str
    icon: str
    flavor: str
    connection_string: str


FLAVOR_OPTIONS = [
    ConnectionFlavor(
        label="Amazon Redshift",
        value="redshift",
        flavor="redshift",
        icon=get_asset_data_url("flavors/redshift.svg"),
        connection_string=connection_service.get_connection_string("redshift"),
    ),
    ConnectionFlavor(
        label="Azure SQL Database",
        value="azure_mssql",
        flavor="mssql",
        icon=get_asset_data_url("flavors/azure_sql.svg"),
        connection_string=connection_service.get_connection_string("mssql"),
    ),
    ConnectionFlavor(
        label="Azure Synapse Analytics",
        value="synapse_mssql",
        flavor="mssql",
        icon=get_asset_data_url("flavors/azure_synapse_table.svg"),
        connection_string=connection_service.get_connection_string("mssql"),
    ),
    ConnectionFlavor(
        label="Microsoft SQL Server",
        value="mssql",
        flavor="mssql",
        icon=get_asset_data_url("flavors/mssql.svg"),
        connection_string=connection_service.get_connection_string("mssql"),
    ),
    ConnectionFlavor(
        label="PostgreSQL",
        value="postgresql",
        flavor="postgresql",
        icon=get_asset_data_url("flavors/postgresql.svg"),
        connection_string=connection_service.get_connection_string("postgresql"),
    ),
    ConnectionFlavor(
        label="Snowflake",
        value="snowflake",
        flavor="snowflake",
        icon=get_asset_data_url("flavors/snowflake.svg"),
        connection_string=connection_service.get_connection_string("snowflake"),
    ),
    ConnectionFlavor(
        label="Databricks",
        value="databricks",
        flavor="databricks",
        icon=get_asset_data_url("flavors/databricks.svg"),
        connection_string=connection_service.get_connection_string("databricks"),
    ),
]
