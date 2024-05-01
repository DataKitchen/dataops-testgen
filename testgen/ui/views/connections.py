import time
import typing

import streamlit as st

import testgen.ui.services.database_service as db
import testgen.ui.services.form_service as fm
import testgen.ui.services.toolbar_service as tb
from testgen.common.database.database_service import empty_cache
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import authentication_service, connection_service
from testgen.ui.session import session


class ConnectionsPage(Page):
    path = "connections"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status or "login",
    ]
    menu_item = MenuItem(icon="compare_arrows", label="Connection")

    def render(self) -> None:
        fm.render_page_header(
            "Connection",
            "https://docs.datakitchen.io/article/dataops-testgen-help/connect-your-database",
            lst_breadcrumbs=[
                {"label": "Overview", "path": "overview"},
                {"label": "Connection", "path": None},
            ],
        )

        project_code = session.project
        dataframe = connection_service.get_connections(project_code)
        connection = dataframe.iloc[0]

        tool_bar = tb.ToolBar(long_slot_count=6, short_slot_count=0, button_slot_count=0, prompt=None)

        show_connection_form(connection, project_code)

        status_container = st.empty()
        create_qc_schema_modal = testgen.Modal("Create QC utility schema", "dk-create-qc-schema-modal", max_width=1100)

        if tool_bar.long_slots[0].button(
            "Test Connection",
            help="Verifies that the connection to the database is working",
            use_container_width=True,
        ):
            verify_connection_works(connection, project_code, status_container)

        if tool_bar.long_slots[-2].button(
            "Create QC Utility schema",
            help="Creates the required Utility schema and related functions in the target database",
            use_container_width=True,
        ):
            create_qc_schema_modal.open()

        if tool_bar.long_slots[-1].button(
            "Table Groups →",
            help="Create or edit Table Groups for the selected Connection",
            use_container_width=True,
        ):
            st.session_state["connection"] = connection.to_dict()

            session.current_page = "connections/table-groups"
            session.current_page_args = {"connection_id": connection["connection_id"]}
            st.experimental_rerun()

        if create_qc_schema_modal.is_open():
            show_create_qc_schema_modal(create_qc_schema_modal, connection)


def show_create_qc_schema_modal(modal, selected_connection):
    with modal.container():
        with st.form("Create QC Utility Schema", clear_on_submit=False):
            skip_schema_creation = st.toggle("Skip schema creation (only populate functions)")
            skip_granting_privileges = st.toggle("Skip granting privileges")
            db_user = st.text_input(label="Admin db user", max_chars=40, placeholder="Optional Field")
            db_password = st.text_input(
                label="Admin db password", max_chars=40, type="password", placeholder="Optional Field"
            )

            submit = st.form_submit_button("Create Schema")

            if submit:
                empty_cache()
                _, bottom_right_column = st.columns([0.20, 0.80])
                operation_status = bottom_right_column.empty()

                operation_status.empty()
                connection_id = selected_connection["connection_id"]
                project_qc_schema = selected_connection["project_qc_schema"]
                operation_status.info(f"Creating QC utility schema '{project_qc_schema}'...")

                create_qc_schema = not skip_schema_creation
                try:
                    connection_service.create_qc_schema(
                        connection_id,
                        create_qc_schema,
                        db_user if db_user else None,
                        db_password if db_password else None,
                        skip_granting_privileges,
                    )
                    operation_status.empty()
                    operation_status.success("Operation has finished successfully.")

                except Exception as e:
                    operation_status.empty()
                    operation_status.error("Error creating QC Utility schema.")
                    error_message = e.args[0]
                    st.text_area("Error Details", value=error_message)


def show_connection_form(connection, project_code):
    with st.form("edit-connection", clear_on_submit=False):
        flavor_options = ["redshift", "snowflake", "mssql", "postgresql"]

        left_column, right_column = st.columns([0.75, 0.25])
        toggle_left_column, _ = st.columns([0.25, 0.75])
        bottom_left_column, bottom_right_column = st.columns([0.25, 0.75])
        button_left_column, _, _ = st.columns([0.20, 0.20, 0.60])

        connection_id = connection["connection_id"]
        connection_name = connection["connection_name"]
        sql_flavor_index = flavor_options.index(connection["sql_flavor"])
        project_port = connection["project_port"]
        project_host = connection["project_host"]
        project_db = connection["project_db"]
        project_user = connection["project_user"]
        url = connection["url"]
        project_qc_schema = connection["project_qc_schema"]
        password = connection["password"]
        max_threads = connection["max_threads"]
        max_query_chars = connection["max_query_chars"]
        connect_by_url = connection["connect_by_url"]

        new_connection = {
            "connection_id": connection_id,
            "project_code": project_code,
            "connection_name": left_column.text_input(
                label="Connection Name",
                max_chars=40,
                value=connection_name,
                help="Your name for this connection. Can be any text.",
            ),
            "sql_flavor": right_column.selectbox(
                label="SQL Flavor",
                options=flavor_options,
                index=sql_flavor_index,
                help="The type of database server that you will connect to. This determines TestGen's drivers and SQL dialect.",
            ),
            "project_port": right_column.text_input(label="Port", max_chars=5, value=project_port),
            "project_host": left_column.text_input(label="Host", max_chars=250, value=project_host),
            "project_db": left_column.text_input(
                label="Database",
                max_chars=100,
                value=project_db,
                help="The name of the database defined on your host where your schemas and tables is present.",
            ),
            "project_user": left_column.text_input(
                label="User",
                max_chars=50,
                value=project_user,
                help="Username to connect to your database.",
            ),
            "password": left_column.text_input(
                label="Password",
                max_chars=50,
                type="password",
                value=password,
                help="Password to connect to your database.",
            ),
            "project_qc_schema": right_column.text_input(
                label="QC Utility Schema",
                max_chars=50,
                value=project_qc_schema,
                help="The name of the schema on your database that will contain TestGen's profiling functions.",
            ),
            "max_threads": right_column.number_input(
                label="Max Threads (Advanced Tuning)",
                min_value=1,
                max_value=8,
                value=max_threads,
                help="Maximum number of concurrent threads that run tests. Default values should be retained unless test queries are failing.",
            ),
            "max_query_chars": right_column.number_input(
                label="Max Expression Length (Advanced Tuning)",
                min_value=500,
                max_value=14000,
                value=max_query_chars,
                help="Some tests are consolidated into queries for maximum performance. Default values should be retained unless test queries are failing.",
            ),
        }

        left_column.markdown("</p>&nbsp;</br>", unsafe_allow_html=True)

        new_connection["connect_by_url"] = toggle_left_column.toggle(
            "Connect by URL",
            value=connect_by_url,
            help="If this switch is set to on, the connection string will be driven by the field below. Only user name and password will be passed per the relevant fields above.",
        )

        connection_string = connection_service.form_overwritten_connection_url(new_connection)
        connection_string_beginning, connection_string_end = connection_string.split("@", 1)
        connection_string_header = connection_string_beginning + "@"

        if not url:
            url = connection_string_end

        new_connection["url"] = bottom_right_column.text_input(
            label="URL Suffix",
            max_chars=200,
            value=url,
            help="Provide a connection string directly. This will override connection parameters if the 'Connect by URL' switch is set.",
        )

        bottom_left_column.text_input(label="URL Prefix", value=connection_string_header, disabled=True)

        submit = button_left_column.form_submit_button(
            "Save Changes",
            disabled=authentication_service.current_user_has_read_role(),
        )
        if submit:
            if not new_connection["password"]:
                st.error("Enter a valid password.")
            else:
                connection_service.edit_connection(new_connection)
                st.success("Changes have been saved successfully.")
                time.sleep(1)


def verify_connection_works(connection, project_code, connection_status_container):
    empty_cache()
    connection_status_container.empty()
    connection_status_container.info("Testing the connection...")

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
            sql_query,
        )
        if len(results) == 1 and results[0][0] == 1:
            qc_error_message = "The connection was successful, but there is an issue with the QC Utility Schema"
            try:
                qc_results = connection_service.test_qc_connection(project_code, connection)
                if not all(qc_results):
                    error_message = f"QC Utility schema confirmation failed. details: {qc_results}"
                    connection_status_container.empty()
                    connection_status_container.error(qc_error_message)
                    st.text_area("Connection Error Details", value=error_message)
                else:
                    connection_status_container.empty()
                    connection_status_container.success("The connection was successful.")
            except Exception as e:
                connection_status_container.empty()
                connection_status_container.error(qc_error_message)
                error_message = e.args[0]
                st.text_area("Connection Error Details", value=error_message)
        else:
            connection_status_container.empty()
            connection_status_container.error("Error completing a query to the database server.")
    except Exception as e:
        connection_status_container.empty()
        connection_status_container.error("Error attempting the Connection.")
        error_message = e.args[0]
        st.text_area("Connection Error Details", value=error_message)
