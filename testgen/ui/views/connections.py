import base64
import logging
import random
import typing
from dataclasses import asdict, dataclass, field

import streamlit as st

from testgen.ui.queries import table_group_queries

try:
    from pyodbc import Error as PyODBCError
except ImportError:
    PyODBCError = None
from sqlalchemy.exc import DatabaseError, DBAPIError

import testgen.ui.services.database_service as db
from testgen.commands.run_profiling import run_profiling_in_background
from testgen.common.database.database_service import empty_cache, get_flavor_service
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection, ConnectionMinimal
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, RUN_TESTS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.ui.assets import get_asset_data_url
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.session import session, temp_value
from testgen.ui.utils import get_cron_sample_handler

LOG = logging.getLogger("testgen")
PAGE_TITLE = "Connection"
CLEAR_SENTINEL = "<clear>"


class ConnectionsPage(Page):
    path = "connections"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon="database",
        label=PAGE_TITLE,
        section="Data Configuration",
        order=1,
    )
    trim_fields: typing.ClassVar[list[str]] = [
        "project_host",
        "project_port",
        "project_user",
        "project_db",
        "url",
        "http_path",
    ]
    encrypted_fields: typing.ClassVar[list[str]] = [
        "project_pw_encrypted",
        "private_key",
        "private_key_passphrase",
        "service_account_key",
    ]

    def render(self, project_code: str, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
            "connect-your-database",
        )

        connections = Connection.select_where(Connection.project_code == project_code)
        connection: Connection = connections[0] if len(connections) > 0 else Connection(
            sql_flavor="postgresql",
            sql_flavor_code="postgresql",
            project_code=project_code,
        )
        has_table_groups = (
            connection.id and len(TableGroup.select_minimal_where(TableGroup.connection_id == connection.connection_id) or []) > 0
        )

        user_is_admin = session.auth.user_has_permission("administer")
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

        def on_connection_updated(connection: dict) -> None:
            set_updated_connection(self._sanitize_connection_input(connection))

        def on_save_connection_clicked(updated_connection):
            is_pristine = lambda value: value in ["", "***"]

            if updated_connection.get("connect_by_url", False):
                url_parts = updated_connection.get("url", "").split("@")
                if len(url_parts) > 1:
                    updated_connection["url"] = url_parts[1]

            if updated_connection.get("connect_by_key"):
                updated_connection["project_pw_encrypted"] = ""
                if is_pristine(updated_connection.get("private_key_passphrase")):
                    del updated_connection["private_key_passphrase"]
                elif updated_connection.get("private_key_passphrase") == CLEAR_SENTINEL:
                    updated_connection["private_key_passphrase"] = ""

                if is_pristine(updated_connection.get("private_key")):
                    del updated_connection["private_key"]
                else:
                    updated_connection["private_key"] = base64.b64decode(updated_connection["private_key"]).decode()
            else:
                updated_connection["private_key"] = ""
                updated_connection["private_key_passphrase"] = ""

                if is_pristine(updated_connection.get("project_pw_encrypted")):
                    del updated_connection["project_pw_encrypted"]
                elif updated_connection.get("project_pw_encrypted") == CLEAR_SENTINEL:
                    updated_connection["project_pw_encrypted"] = ""

            if updated_connection.get("connect_with_identity"):
                updated_connection["project_user"] = ""
                updated_connection["project_pw_encrypted"] = ""

            updated_connection["sql_flavor"] = self._get_sql_flavor_from_value(updated_connection["sql_flavor_code"]).flavor

            set_save(True)
            set_updated_connection(self._sanitize_connection_input(updated_connection))

        def on_test_connection_clicked(updated_connection: dict) -> None:
            password = updated_connection.get("project_pw_encrypted")
            private_key = updated_connection.get("private_key")
            private_key_passphrase = updated_connection.get("private_key_passphrase")
            is_pristine = lambda value: value in ["", "***"]

            if is_pristine(password):
                del updated_connection["project_pw_encrypted"]

            if is_pristine(private_key):
                del updated_connection["private_key"]
            else:
                updated_connection["private_key"] = base64.b64decode(updated_connection["private_key"]).decode()

            if is_pristine(private_key_passphrase):
                del updated_connection["private_key_passphrase"]
            elif updated_connection.get("private_key_passphrase") == CLEAR_SENTINEL:
                updated_connection["private_key_passphrase"] = ""

            if updated_connection.get("connect_with_identity"):
                updated_connection["project_user"] = ""
                updated_connection["project_pw_encrypted"] = ""

            updated_connection["sql_flavor"] = self._get_sql_flavor_from_value(updated_connection["sql_flavor_code"]).flavor

            set_check_status(True)
            set_updated_connection(self._sanitize_connection_input(updated_connection))

        def on_setup_table_group_clicked(*_args) -> None:
            table_group_queries.reset_table_group_preview()
            self.setup_data_configuration(project_code, connection.connection_id)

        results = None
        for key, value in get_updated_connection().items():
            setattr(connection, key, value)

        connection_string: str | None = None
        flavor_service = get_flavor_service(connection.sql_flavor)
        flavor_service.init({**connection.to_dict(), "project_pw_encrypted": "<password>"})
        connection_string = flavor_service.get_connection_string().replace("%3E", ">").replace("%3C", "<")

        if should_save():
            success = True
            try:
                connection.save()
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
                "generated_connection_url": connection_string,
                "results": results,
            },
            on_change_handlers={
                "TestConnectionClicked": on_test_connection_clicked,
                "SaveConnectionClicked": on_save_connection_clicked,
                "SetupTableGroupClicked": on_setup_table_group_clicked,
                "ConnectionUpdated": on_connection_updated,
            },
        )

    def _get_sql_flavor_from_value(self, value: str) -> "ConnectionFlavor | None":
        match = [f for f in FLAVOR_OPTIONS if f.value == value]
        if match:
            return match[0]
        return None

    def _sanitize_connection_input(self, connection: dict) -> dict:
        if not connection:
            return connection

        sanitized_connection_input = {}
        for key, value in connection.items():
            sanitized_value = value
            if isinstance(value, str) and key in self.trim_fields:
                sanitized_value = value.strip()
            if isinstance(value, str) and key in self.encrypted_fields:
                sanitized_value = value if value != "" else None
            sanitized_connection_input[key] = sanitized_value
        return sanitized_connection_input

    def _format_connection(self, connection: Connection, should_test: bool = False) -> dict:
        formatted_connection = format_connection(connection)
        if should_test:
            formatted_connection["status"] = asdict(self.test_connection(connection))
        return formatted_connection

    def test_connection(self, connection: Connection) -> "ConnectionStatus":
        empty_cache()
        try:
            sql_query = "select 1;"
            results = db.fetch_from_target_db(connection, sql_query)
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
            if connection.connect_by_key and not connection.private_key:
                details = "The private key is missing."
            LOG.exception("Error testing database connection")
            return ConnectionStatus(message="Error attempting the connection.", details=details, successful=False)

    @st.dialog(title="Data Configuration Setup")
    @with_database_session
    def setup_data_configuration(self, project_code: str, connection_id: str) -> None:
        def on_save_table_group_clicked(payload: dict) -> None:
            table_group: dict = payload["table_group"]
            table_group_verified: bool = payload.get("table_group_verified", False)
            run_profiling: bool = payload.get("run_profiling", False)
            standard_test_suite: dict | None = payload.get("standard_test_suite", None)
            monitor_test_suite: dict | None = payload.get("monitor_test_suite", None)

            set_new_table_group(table_group)
            mark_for_preview(True)
            set_table_group_verified(table_group_verified)
            set_run_profiling(run_profiling)
            set_standard_test_suite_data(standard_test_suite)
            set_monitor_test_suite_data(monitor_test_suite)
            mark_for_save(True)

        def on_preview_table_group(payload: dict) -> None:
            table_group = payload["table_group"]
            verify_table_access = payload.get("verify_access") or False

            set_new_table_group(table_group)
            mark_for_preview(True)
            mark_for_access_preview(verify_table_access)

        def on_close_clicked(_params: dict) -> None:
            set_close_dialog(True)

        get_close_dialog, set_close_dialog = temp_value(f"connections:{connection_id}:close", default=False)
        if (get_close_dialog()):
            st.rerun()

        get_new_table_group, set_new_table_group = temp_value(
            f"connections:{connection_id}:table_group",
            default={},
        )
        get_run_profiling, set_run_profiling = temp_value(
            f"connections:{connection_id}:run_profiling",
            default=False,
        )

        results = None
        table_group_data = get_new_table_group()
        should_run_profiling = get_run_profiling()
        should_preview, mark_for_preview = temp_value(
            f"connections:{connection_id}:tg_preview",
            default=False,
        )
        should_verify_access, mark_for_access_preview = temp_value(
            f"connections:{connection_id}:tg_preview_access",
            default=False,
        )
        is_table_group_verified, set_table_group_verified = temp_value(
            f"connections:{connection_id}:tg_verified",
            default=False,
        )
        should_save, mark_for_save = temp_value(
            f"connections:{connection_id}:tg_save",
            default=False,
        )
        standard_cron_sample_result, on_get_standard_cron_sample = get_cron_sample_handler(f"connections:{connection_id}:standard_cron_expr_validation")
        monitor_cron_sample_result, on_get_monitor_cron_sample = get_cron_sample_handler(f"connections:{connection_id}:monitor_cron_expr_validation")
        get_standard_test_suite_data, set_standard_test_suite_data = temp_value(
            f"connections:{connection_id}:test_suite_data",
            default={
                "generate": False,
                "name": "",
                "schedule": "",
                "timezone": "",
            },
        )
        get_monitor_test_suite_data, set_monitor_test_suite_data = temp_value(
            f"connections:{connection_id}:monitor_suite_data",
            default={
                "generate": False,
                "monitor_lookback": 0,
                "schedule": "",
                "timezone": "",
                "predict_sensitivity": 0,
                "predict_min_lookback": 0,
                "predict_exclude_weekends": False,
                "predict_holiday_codes": None,
            },
        )

        add_scorecard_definition = table_group_data.pop("add_scorecard_definition", False)
        table_group = TableGroup(
            project_code=project_code,
            **{
                **(table_group_data or {}),
                "connection_id": connection_id,
            },
        )

        table_group_preview = None
        save_data_chars = None
        if should_preview():
            table_group_preview, save_data_chars = table_group_queries.get_table_group_preview(
                table_group,
                verify_table_access=should_verify_access(),
            )

        run_profiling = False
        generate_test_suite = False
        generate_monitor_suite = False
        standard_test_suite = None
        monitor_test_suite = None
        if should_save():
            success = True
            message = None

            if is_table_group_verified():
                try:
                    table_group.save(add_scorecard_definition)

                    if save_data_chars:
                        try:
                            save_data_chars(table_group.id)
                        except Exception:
                            LOG.exception("Data characteristics refresh encountered errors")

                    standard_test_suite_data = get_standard_test_suite_data() or {}
                    if standard_test_suite_data.get("generate"):
                        generate_test_suite = True
                        standard_test_suite = TestSuite(
                            project_code=project_code,
                            test_suite=standard_test_suite_data["name"],
                            connection_id=table_group.connection_id,
                            table_groups_id=table_group.id,
                            export_to_observability=False,
                            dq_score_exclude=False,
                            is_monitor=False,
                            monitor_lookback=0,
                            predict_min_lookback=0,
                        )
                        standard_test_suite.save()

                        JobSchedule(
                            project_code=project_code,
                            key=RUN_TESTS_JOB_KEY,
                            cron_expr=standard_test_suite_data["schedule"],
                            cron_tz=standard_test_suite_data["timezone"],
                            args=[],
                            kwargs={"test_suite_id": str(standard_test_suite.id)},
                        ).save()

                    monitor_test_suite_data = get_monitor_test_suite_data() or {}
                    if monitor_test_suite_data.get("generate"):
                        generate_monitor_suite = True
                        monitor_test_suite = TestSuite(
                            project_code=project_code,
                            test_suite=f"{table_group.table_groups_name} Monitors",
                            connection_id=table_group.connection_id,
                            table_groups_id=table_group.id,
                            export_to_observability=False,
                            dq_score_exclude=True,
                            is_monitor=True,
                            monitor_lookback=monitor_test_suite_data.get("monitor_lookback") or 14,
                            predict_min_lookback=monitor_test_suite_data.get("predict_min_lookback") or 30,
                            predict_sensitivity=monitor_test_suite_data.get("predict_sensitivity") or "medium",
                            predict_exclude_weekends=monitor_test_suite_data.get("predict_exclude_weekends") or False,
                            predict_holiday_codes=monitor_test_suite_data.get("predict_holiday_codes") or None,
                        )
                        monitor_test_suite.save()

                        JobSchedule(
                            project_code=project_code,
                            key=RUN_MONITORS_JOB_KEY,
                            cron_expr=monitor_test_suite_data.get("schedule"),
                            cron_tz=monitor_test_suite_data.get("timezone"),
                            args=[],
                            kwargs={"test_suite_id": str(monitor_test_suite.id)},
                        ).save()

                    if standard_test_suite or monitor_test_suite:
                        table_group.default_test_suite_id = standard_test_suite.id if standard_test_suite else None
                        table_group.monitor_test_suite_id = monitor_test_suite.id if monitor_test_suite else None
                        table_group.save()

                    if should_run_profiling:
                        try:
                            run_profiling = True
                            run_profiling_in_background(table_group.id)
                            message = f"Profiling run started for table group {table_group.table_groups_name}."
                        except Exception as error:
                            message = "Profiling run encountered errors"
                            success = False
                            LOG.exception(message)
                    else:
                        LOG.info("Table group %s created", table_group.id)
                        st.rerun()
                except Exception as error:
                    message = "Error creating table group"
                    success = False
                    LOG.exception(message)

                results = {
                    "success": success,
                    "message": message,
                    "test_suite_name": standard_test_suite.test_suite if standard_test_suite else None,
                    "run_profiling": run_profiling,
                    "generate_test_suite": generate_test_suite,
                    "generate_monitor_suite": generate_monitor_suite,
                }
            else:
                results = {
                    "success": False,
                    "message": "Verify the table group before saving",
                    "run_profiling": False,
                    "generate_test_suite": False,
                    "generate_monitor_suite": False,
                    "test_suite_name": None,
                }

        return testgen.table_group_wizard(
            key="setup_data_configuration",
            data={
                "project_code": project_code,
                "table_group": table_group.to_dict(json_safe=True),
                "table_group_preview": table_group_preview,
                "steps": [
                    "tableGroup",
                    "testTableGroup",
                    "runProfiling",
                    "testSuite",
                    "monitorSuite",
                ],
                "results": results,
                "standard_cron_sample": standard_cron_sample_result(),
                "monitor_cron_sample": monitor_cron_sample_result(),
            },
            on_SaveTableGroupClicked_change=on_save_table_group_clicked,
            on_PreviewTableGroupClicked_change=on_preview_table_group,
            on_CloseClicked_change=on_close_clicked,
            on_GetCronSample_change=on_get_monitor_cron_sample,
            on_GetCronSampleAux_change=on_get_standard_cron_sample,
        )


@dataclass(frozen=True, slots=True)
class ConnectionStatus:
    message: str
    successful: bool
    details: str | None = field(default=None)
    _: float = field(default_factory=random.random)


def is_open_ssl_error(error: Exception):
    return (
        error.args
        and len(error.args) > 1
        and isinstance(error.args[1], list)
        and len(error.args[1]) > 0
        and type(error.args[1][0]).__name__ == "OpenSSLError"
    )


def format_connection(connection: Connection | ConnectionMinimal) -> dict:
    formatted_connection = connection.to_dict(json_safe=True)

    if formatted_connection.get("project_pw_encrypted"):
        formatted_connection["project_pw_encrypted"] = "***"
    if formatted_connection.get("private_key"):
        formatted_connection["private_key"] = "***"  # S105
    if formatted_connection.get("private_key_passphrase"):
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


FLAVOR_OPTIONS = [
    ConnectionFlavor(
        label="Amazon Redshift",
        value="redshift",
        flavor="redshift",
        icon=get_asset_data_url("flavors/redshift.svg"),
    ),
    ConnectionFlavor(
        label="Amazon Redshift Spectrum",
        value="redshift_spectrum",
        flavor="redshift_spectrum",
        icon=get_asset_data_url("flavors/redshift.svg"),
    ),
    ConnectionFlavor(
        label="Azure SQL Database",
        value="azure_mssql",
        flavor="mssql",
        icon=get_asset_data_url("flavors/azure_sql.svg"),
    ),
    ConnectionFlavor(
        label="Azure Synapse Analytics",
        value="synapse_mssql",
        flavor="mssql",
        icon=get_asset_data_url("flavors/azure_synapse_table.svg"),
    ),
    ConnectionFlavor(
        label="Databricks",
        value="databricks",
        flavor="databricks",
        icon=get_asset_data_url("flavors/databricks.svg"),
    ),
    ConnectionFlavor(
        label="Google BigQuery",
        value="bigquery",
        flavor="bigquery",
        icon=get_asset_data_url("flavors/bigquery.svg"),
    ),
    ConnectionFlavor(
        label="Microsoft SQL Server",
        value="mssql",
        flavor="mssql",
        icon=get_asset_data_url("flavors/mssql.svg"),
    ),
    ConnectionFlavor(
        label="PostgreSQL",
        value="postgresql",
        flavor="postgresql",
        icon=get_asset_data_url("flavors/postgresql.svg"),
    ),
    ConnectionFlavor(
        label="Snowflake",
        value="snowflake",
        flavor="snowflake",
        icon=get_asset_data_url("flavors/snowflake.svg"),
    ),
]
