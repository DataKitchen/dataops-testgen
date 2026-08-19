import base64
import logging
import typing
from dataclasses import asdict, dataclass

import streamlit as st

from testgen import settings
from testgen.common.database.connection_service import ConnectionStatus, normalize_auth_fields, test_connection_status
from testgen.common.database.database_service import get_flavor_service
from testgen.common.database.flavor.flavor_service import resolve_connection_params
from testgen.common.enums import JobSource
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, FLAVOR_CODE_TO_LABEL
from testgen.common.models import with_database_session
from testgen.common.models.connection import Connection, ConnectionMinimal
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.scheduler import RUN_TESTS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.monitor_service import enable_monitoring
from testgen.ui.assets import get_asset_data_url
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import table_group_queries
from testgen.ui.services.query_cache import (
    get_connection,
    select_connections_where,
    select_table_groups_minimal_where,
)
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
            "connect-your-database/manage-connections/",
        )

        connections = select_connections_where(Connection.project_code == project_code)
        connection: Connection = connections[0] if len(connections) > 0 else Connection(
            sql_flavor="postgresql",
            sql_flavor_code="postgresql",
            project_code=project_code,
        )
        has_table_groups = (
            connection.id and len(select_table_groups_minimal_where(TableGroup.connection_id == connection.connection_id) or []) > 0
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

            # Databricks OAuth sets connect_by_key but stores the Client Secret in project_pw_encrypted,
            # so it follows the password path rather than the private-key path.
            uses_private_key = (
                updated_connection.get("connect_by_key")
                and updated_connection.get("sql_flavor_code") != "databricks"
            )
            if uses_private_key:
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
            st.session_state["connections:setup_dialog"] = connection.connection_id

        results = None
        for key, value in get_updated_connection().items():
            setattr(connection, key, value)

        connection_string: str | None = None
        flavor_service = get_flavor_service(connection.sql_flavor)
        params = resolve_connection_params({**connection.to_dict(), "project_pw_encrypted": "<password>"})
        connection_string = flavor_service.get_connection_string(params).replace("%3E", ">").replace("%3C", "<")

        if should_save():
            success = True
            try:
                normalize_auth_fields(connection)
                connection.save()
                select_connections_where.clear()
                get_connection.clear()
                message = "Changes have been saved successfully."
            except ValueError as error:
                message = str(error)
                success = False
            except Exception as error:
                message = "Something went wrong while creating the connection."
                success = False
                LOG.exception(message)

            results = {
                "success": success,
                "message": message,
            }

        setup_wizard_data = None
        setup_wizard_handlers = {}
        if setup_connection_id := st.session_state.get("connections:setup_dialog"):
            setup_wizard_data, setup_wizard_handlers = self.setup_data_configuration(project_code, setup_connection_id)

        testgen.connections_widget(
            key="connections",
            data={
                "project_code": project_code,
                "connection": self._format_connection(connection, should_test=should_check_status()),
                "has_table_groups": has_table_groups,
                "flavors": [asdict(flavor) for flavor in VISIBLE_FLAVOR_OPTIONS],
                "permissions": {
                    "is_admin": user_is_admin,
                },
                "generated_connection_url": connection_string,
                "results": results,
                "setup_wizard": setup_wizard_data,
            },
            on_TestConnectionClicked_change=on_test_connection_clicked,
            on_SaveConnectionClicked_change=on_save_connection_clicked,
            on_SetupTableGroupClicked_change=on_setup_table_group_clicked,
            on_ConnectionUpdated_change=on_connection_updated,
            **setup_wizard_handlers,
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

    def test_connection(self, connection: Connection) -> ConnectionStatus:
        try:
            normalize_auth_fields(connection)
        except ValueError as error:
            return ConnectionStatus(message=str(error), successful=False, details=None)
        return test_connection_status(connection)

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
            st.session_state.pop("connections:setup_dialog", None)

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
            default={"generate": False},
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
                            kwargs={"test_suite_id": str(standard_test_suite.id)},
                        ).save()

                    monitor_test_suite_data = get_monitor_test_suite_data() or {}
                    if monitor_test_suite_data.get("generate"):
                        generate_monitor_suite = True
                        monitor_test_suite, _ = enable_monitoring(
                            table_group,
                            monitor_test_suite_data.get("schedule"),
                            monitor_test_suite_data.get("timezone") or "UTC",
                            suite_attrs={
                                "monitor_lookback": monitor_test_suite_data.get("monitor_lookback"),
                                "monitor_regenerate_freshness": monitor_test_suite_data.get(
                                    "monitor_regenerate_freshness"
                                ),
                                "predict_min_lookback": monitor_test_suite_data.get("predict_min_lookback"),
                                "predict_sensitivity": monitor_test_suite_data.get("predict_sensitivity"),
                                "predict_exclude_weekends": monitor_test_suite_data.get("predict_exclude_weekends"),
                                "predict_holiday_codes": monitor_test_suite_data.get("predict_holiday_codes"),
                            },
                        )

                    if standard_test_suite or monitor_test_suite:
                        table_group.default_test_suite_id = standard_test_suite.id if standard_test_suite else None
                        table_group.monitor_test_suite_id = monitor_test_suite.id if monitor_test_suite else None
                        table_group.save()

                    if should_run_profiling:
                        try:
                            run_profiling = True
                            JobExecution.submit(
                                job_key="run-profile",
                                kwargs={"table_group_id": str(table_group.id)},
                                source=JobSource.ui,
                                project_code=table_group.project_code,
                            )
                            message = f"Profiling run started for table group {table_group.table_groups_name}."
                        except Exception as error:
                            message = "Profiling run encountered errors"
                            success = False
                            LOG.exception(message)
                    else:
                        LOG.info("Table group %s created", table_group.id)
                except Exception as error:
                    message = "Something went wrong while creating the table group."
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

        wizard_data = {
            "dialog": {"open": True, "title": "Data Configuration Setup"},
            "project_code": project_code,
            "table_group": table_group.to_dict(json_safe=True),
            "permissions": {
                "can_view_pii": session.auth.user_has_permission("view_pii"),
            },
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
        }
        wizard_handlers = {
            "on_SaveTableGroupClicked_change": on_save_table_group_clicked,
            "on_PreviewTableGroupClicked_change": on_preview_table_group,
            "on_CloseClicked_change": on_close_clicked,
            "on_GetCronSample_change": on_get_monitor_cron_sample,
            "on_GetCronSampleAux_change": on_get_standard_cron_sample,
        }
        return wizard_data, wizard_handlers


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


# Labels and families come from the shared source in ``common/flavors.py`` (the
# same labels MCP uses); only the icon + display order are UI-specific.
_FLAVOR_ICONS: dict[str, str] = {
    "redshift": "flavors/redshift.svg",
    "redshift_spectrum": "flavors/redshift.svg",
    "azure_mssql": "flavors/azure_sql.svg",
    "synapse_mssql": "flavors/azure_synapse_table.svg",
    "databricks": "flavors/databricks.svg",
    "bigquery": "flavors/bigquery.svg",
    "onelake_mssql": "flavors/onelake.svg",
    "mssql": "flavors/mssql.svg",
    "oracle": "flavors/oracle.svg",
    "postgresql": "flavors/postgresql.svg",
    "sap_hana": "flavors/sap_hana.svg",
    "salesforce_data360": "flavors/salesforce_data360.svg",
    "snowflake": "flavors/snowflake.svg",
}

FLAVOR_OPTIONS = [
    ConnectionFlavor(
        value=code,
        label=str(FLAVOR_CODE_TO_LABEL[code]),
        flavor=FLAVOR_CODE_TO_FAMILY[code],
        icon=get_asset_data_url(icon),
    )
    for code, icon in _FLAVOR_ICONS.items()
]

# SAP HANA is hidden in the Docker image because pyhdbcli is glibc-only and fails to load on Alpine/musl.
VISIBLE_FLAVOR_OPTIONS = [
    f for f in FLAVOR_OPTIONS
    if not (settings.CHECK_FOR_LATEST_VERSION == "docker" and f.value == "sap_hana")
]
