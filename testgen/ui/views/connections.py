import dataclasses
import logging
import os
import time
import typing

import streamlit as st

import testgen.ui.services.database_service as db
from testgen.commands.run_setup_profiling_tools import get_setup_profiling_tools_queries
from testgen.common.database.database_service import empty_cache
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import authentication_service, connection_service
from testgen.ui.session import session

LOG = logging.getLogger("testgen")


class ConnectionsPage(Page):
    path = "connections"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="database", label="Data Configuration", order=4)

    def render(self, project_code: str, **_kwargs) -> None:
        dataframe = connection_service.get_connections(project_code)
        connection = dataframe.iloc[0]

        testgen.page_header(
            "Connection",
            "https://docs.datakitchen.io/article/dataops-testgen-help/connect-your-database",
        )

        _, actions_column = st.columns([.1, .9])
        testgen.flex_row_end(actions_column)

        enable_table_groups = connection["project_host"] and connection["project_db"] and connection["project_qc_schema"]

        with st.container(border=True):
            self.show_connection_form(connection, "edit", project_code)

        if actions_column.button(
            "Configure QC Utility Schema",
            help="Creates the required Utility schema and related functions in the target database",
        ):
            self.create_qc_schema_dialog(connection)

        if actions_column.button(
            f":{'gray' if not enable_table_groups else 'green'}[Table Groups　→]",
            help="Create or edit Table Groups for the Connection",
        ):
            self.router.navigate(
                "connections:table-groups",
                {"connection_id": connection["connection_id"]},
            )

    @st.dialog(title="Configure QC Utility Schema")
    def create_qc_schema_dialog(self, selected_connection):
        connection_id = selected_connection["connection_id"]
        project_qc_schema = selected_connection["project_qc_schema"]
        sql_flavor = selected_connection["sql_flavor"]
        user = selected_connection["project_user"]

        create_qc_schema = st.toggle("Create QC Utility Schema", value=True)
        grant_privileges = st.toggle("Grant access privileges to TestGen user", value=True)

        user_role = None

        # TODO ALEX: This textbox may be needed if we want to grant permissions to user role
        # if sql_flavor == "snowflake":
        #    user_role_textbox_label = f"Primary role for database user {user}"
        #    user_role = st.text_input(label=user_role_textbox_label, max_chars=100)

        admin_credentials_expander = st.expander("Admin credential options", expanded=True)
        with admin_credentials_expander:
            admin_connection_option_index = 0
            admin_connection_options = ["Do not use admin credentials", "Use admin credentials with Password"]
            if sql_flavor == "snowflake":
                admin_connection_options.append("Use admin credentials with Key-Pair")

            admin_connection_option = st.radio(
                "Admin credential options",
                label_visibility="hidden",
                options=admin_connection_options,
                index=admin_connection_option_index,
                horizontal=True,
            )

            st.markdown("</p>&nbsp;</br>", unsafe_allow_html=True)

            db_user = None
            db_password = None
            admin_private_key_passphrase = None
            admin_private_key = None
            if admin_connection_option == admin_connection_options[0]:
                st.markdown(":orange[User created in the connection dialog will be used.]")
            else:
                db_user = st.text_input(label="Admin db user", max_chars=40)
            if admin_connection_option == admin_connection_options[1]:
                db_password = st.text_input(
                    label="Admin db password", max_chars=40, type="password"
                )
                st.markdown(":orange[Note: Admin credentials are not stored, are only used for this operation.]")

            if len(admin_connection_options) > 2 and admin_connection_option == admin_connection_options[2]:
                admin_private_key_passphrase = st.text_input(
                    label="Private Key Passphrase",
                    key="create-qc-schema-private-key-password",
                    type="password",
                    max_chars=200,
                    help="Passphrase used while creating the private Key (leave empty if not applicable)",
                )

                admin_uploaded_file = st.file_uploader("Upload private key (rsa_key.p8)", key="admin-uploaded-file")
                if admin_uploaded_file:
                    admin_private_key = admin_uploaded_file.getvalue().decode("utf-8")

                st.markdown(":orange[Note: Admin credentials are not stored, are only used for this operation.]")

        submit = st.button("Update Configuration")

        if submit:
            empty_cache()
            script_expander = st.expander("Script Details")

            operation_status = st.empty()
            operation_status.info(f"Configuring QC Utility Schema '{project_qc_schema}'...")

            try:
                skip_granting_privileges = not grant_privileges
                queries = get_setup_profiling_tools_queries(sql_flavor, create_qc_schema, skip_granting_privileges, project_qc_schema, user, user_role)
                with script_expander:
                    st.code(
                        os.linesep.join(queries),
                        language="sql",
                        line_numbers=True)

                connection_service.create_qc_schema(
                    connection_id,
                    create_qc_schema,
                    db_user if db_user else None,
                    db_password if db_password else None,
                    skip_granting_privileges,
                    admin_private_key_passphrase=admin_private_key_passphrase,
                    admin_private_key=admin_private_key,
                    user_role=user_role,
                )
                operation_status.empty()
                operation_status.success("Operation has finished successfully.")

            except Exception as e:
                operation_status.empty()
                operation_status.error("Error configuring QC Utility Schema.")
                error_message = e.args[0]
                st.text_area("Error Details", value=error_message)

    def show_connection_form(self, selected_connection, mode, project_code):
        flavor_options = ["redshift", "snowflake", "mssql", "postgresql"]
        connection_options = ["Connect by Password", "Connect by Key-Pair"]

        left_column, right_column = st.columns([0.75, 0.25])

        mid_column = st.columns(1)[0]
        url_override_toogle_container = st.container()
        bottom_left_column, bottom_right_column = st.columns([0.25, 0.75])
        button_left_column, button_right_column = st.columns([0.20, 0.80])
        connection_status_wrapper = st.container()

        connection_id = selected_connection["connection_id"] if mode == "edit" else None
        connection_name = selected_connection["connection_name"] if mode == "edit" else ""
        sql_flavor_index = flavor_options.index(selected_connection["sql_flavor"]) if mode == "edit" else 0
        project_port = selected_connection["project_port"] if mode == "edit" else ""
        project_host = selected_connection["project_host"] if mode == "edit" else ""
        project_db = selected_connection["project_db"] if mode == "edit" else ""
        project_user = selected_connection["project_user"] if mode == "edit" else ""
        url = selected_connection["url"] if mode == "edit" else ""
        project_qc_schema = selected_connection["project_qc_schema"] if mode == "edit" else "qc"
        password = selected_connection["password"] if mode == "edit" else ""
        max_threads = selected_connection["max_threads"] if mode == "edit" else 4
        max_query_chars = selected_connection["max_query_chars"] if mode == "edit" else 10000
        connect_by_url = selected_connection["connect_by_url"] if mode == "edit" else False
        connect_by_key = selected_connection["connect_by_key"] if mode == "edit" else False
        connection_option_index = 1 if connect_by_key else 0
        private_key = selected_connection["private_key"] if mode == "edit" else None
        private_key_passphrase = selected_connection["private_key_passphrase"] if mode == "edit" else ""

        new_connection = {
            "connection_id": connection_id,
            "project_code": project_code,
            "private_key": private_key,
            "private_key_passphrase": private_key_passphrase,
            "password": password,
            "url": url,
            "max_threads": right_column.number_input(
                label="Max Threads (Advanced Tuning)",
                min_value=1,
                max_value=8,
                value=max_threads,
                help=(
                    "Maximum number of concurrent threads that run tests. Default values should be retained unless "
                    "test queries are failing."
                ),
                key=f"connections:form:max-threads:{connection_id or 0}",
            ),
            "max_query_chars": right_column.number_input(
                label="Max Expression Length (Advanced Tuning)",
                min_value=500,
                max_value=14000,
                value=max_query_chars,
                help="Some tests are consolidated into queries for maximum performance. Default values should be retained unless test queries are failing.",
                key=f"connections:form:max-length:{connection_id or 0}",
            ),
            "connection_name": left_column.text_input(
                label="Connection Name",
                max_chars=40,
                value=connection_name,
                help="Your name for this connection. Can be any text.",
                key=f"connections:form:name:{connection_id or 0}",
            ),
            "sql_flavor": left_column.selectbox(
                label="SQL Flavor",
                options=flavor_options,
                index=sql_flavor_index,
                help="The type of database server that you will connect to. This determines TestGen's drivers and SQL dialect.",
                key=f"connections:form:flavor:{connection_id or 0}",
            )
        }

        st.session_state.disable_url_widgets = connect_by_url

        new_connection["project_port"] = right_column.text_input(
            label="Port",
            max_chars=5,
            value=project_port,
            disabled=st.session_state.disable_url_widgets,
            key=f"connections:form:port:{connection_id or 0}",
        )
        new_connection["project_host"] = left_column.text_input(
            label="Host",
            max_chars=250,
            value=project_host,
            disabled=st.session_state.disable_url_widgets,
            key=f"connections:form:host:{connection_id or 0}",
        )
        new_connection["project_db"] = left_column.text_input(
            label="Database",
            max_chars=100,
            value=project_db,
            help="The name of the database defined on your host where your schemas and tables is present.",
            disabled=st.session_state.disable_url_widgets,
            key=f"connections:form:database:{connection_id or 0}",
        )

        new_connection["project_user"] = left_column.text_input(
            label="User",
            max_chars=50,
            value=project_user,
            help="Username to connect to your database.",
            key=f"connections:form:user:{connection_id or 0}",
        )

        new_connection["project_qc_schema"] = right_column.text_input(
            label="QC Utility Schema",
            max_chars=50,
            value=project_qc_schema,
            help="The name of the schema on your database that will contain TestGen's profiling functions.",
            key=f"connections:form:qcschema:{connection_id or 0}",
        )

        if new_connection["sql_flavor"] == "snowflake":
            mid_column.divider()

            connection_option = mid_column.radio(
                "Connection options",
                options=connection_options,
                index=connection_option_index,
                horizontal=True,
                help="Connection strategy",
                key=f"connections:form:type_options:{connection_id or 0}",
            )

            new_connection["connect_by_key"] = connection_option == "Connect by Key-Pair"
            password_column = mid_column
        else:
            new_connection["connect_by_key"] = False
            password_column = left_column

        uploaded_file = None

        if new_connection["connect_by_key"]:
            new_connection["private_key_passphrase"] = mid_column.text_input(
                label="Private Key Passphrase",
                type="password",
                max_chars=200,
                value=private_key_passphrase,
                help="Passphrase used while creating the private Key (leave empty if not applicable)",
                key=f"connections:form:passphrase:{connection_id or 0}",
            )

            uploaded_file = mid_column.file_uploader("Upload private key (rsa_key.p8)")
        else:
            new_connection["password"] = password_column.text_input(
                label="Password",
                max_chars=50,
                type="password",
                value=password,
                help="Password to connect to your database.",
                key=f"connections:form:password:{connection_id or 0}",
            )

        mid_column.divider()

        url_override_help_text = "If this switch is set to on, the connection string will be driven by the field below. "
        if new_connection["connect_by_key"]:
            url_override_help_text += "Only user name will be passed per the relevant fields above."
        else:
            url_override_help_text += "Only user name and password will be passed per the relevant fields above."

        def on_connect_by_url_change():
            value = st.session_state.connect_by_url_toggle
            st.session_state.disable_url_widgets = value

        new_connection["connect_by_url"] = url_override_toogle_container.toggle(
            "URL override",
            value=connect_by_url,
            key="connect_by_url_toggle",
            help=url_override_help_text,
            on_change=on_connect_by_url_change,
        )

        if new_connection["connect_by_url"]:
            connection_string = connection_service.form_overwritten_connection_url(new_connection)
            connection_string_beginning, connection_string_end = connection_string.split("@", 1)
            connection_string_header = connection_string_beginning + "@"
            connection_string_header = connection_string_header.replace("%3E", ">")
            connection_string_header = connection_string_header.replace("%3C", "<")

            if not url:
                url = connection_string_end

            new_connection["url"] = bottom_right_column.text_input(
                label="URL Suffix",
                max_chars=200,
                value=url,
                help="Provide a connection string directly. This will override connection parameters if the 'Connect by URL' switch is set.",
            )

            bottom_left_column.text_input(label="URL Prefix", value=connection_string_header, disabled=True)

        bottom_left_column.markdown("</p>&nbsp;</br>", unsafe_allow_html=True)

        testgen.flex_row_end(button_right_column)
        submit = button_right_column.button(
            "Save" if mode == "edit" else "Add Connection",
            disabled=authentication_service.current_user_has_read_role(),
        )

        if submit:
            if not new_connection["password"] and not new_connection["connect_by_key"]:
                st.error("Enter a valid password.")
            else:
                if uploaded_file:
                    new_connection["private_key"] = uploaded_file.getvalue().decode("utf-8")

                if mode == "edit":
                    connection_service.edit_connection(new_connection)
                else:
                    connection_service.add_connection(new_connection)
                success_message = (
                    "Changes have been saved successfully. "
                    if mode == "edit"
                    else "New connection added successfully. "
                )
                st.success(success_message)
                time.sleep(1)
                st.rerun()

        test_connection = button_left_column.button("Test Connection")

        if test_connection:
            single_element_container = connection_status_wrapper.empty()
            single_element_container.info("Connecting ...")
            connection_status = self.test_connection(new_connection)

            with single_element_container.container():
                renderer = {
                    True: st.success,
                    False: st.error,
                }[connection_status.successful]

                renderer(connection_status.message)
                if not connection_status.successful and connection_status.details:
                    st.caption("Connection Error Details")

                    with st.container(border=True):
                        st.markdown(connection_status.details)
        else:
            # This is needed to fix a strange bug in Streamlit when using dialog + input fields + button
            # If an input field is changed and the button is clicked immediately (without unfocusing the input first),
            # two fragment reruns happen successively, one for unfocusing the input and the other for clicking the button
            # Some or all (it seems random) of the input fields disappear when this happens
            time.sleep(0.1)

    def test_connection(self, connection: dict) -> "ConnectionStatus":
        if connection["connect_by_key"] and connection["connection_id"] is None:
            return ConnectionStatus(
                message="Please add the connection before testing it (so that we can get your private key file).",
                successful=False,
            )

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
                connection["private_key"],
                connection["private_key_passphrase"],
                sql_query,
            )
            connection_successful = len(results) == 1 and results[0][0] == 1

            if not connection_successful:
                return ConnectionStatus(message="Error completing a query to the database server.", successful=False)

            qc_error_message = "The connection was successful, but there is an issue with the QC Utility Schema"
            try:
                qc_results = connection_service.test_qc_connection(connection["project_code"], connection)
                if not all(qc_results):
                    return ConnectionStatus(
                        message=qc_error_message,
                        details=f"QC Utility Schema confirmation failed. details: {qc_results}",
                        successful=False,
                    )
                return ConnectionStatus(message="The connection was successful.", successful=True)
            except Exception as error:
                return ConnectionStatus(message=qc_error_message, details=error.args[0], successful=False)
        except Exception as error:
            return ConnectionStatus(message="Error attempting the Connection.", details=error.args[0], successful=False)


@dataclasses.dataclass(frozen=True, slots=True)
class ConnectionStatus:
    message: str
    successful: bool
    details: str | None = dataclasses.field(default=None)
