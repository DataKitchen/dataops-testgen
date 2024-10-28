import logging
import os
import time
import typing
from functools import partial

import streamlit as st
import streamlit_pydantic as sp
from pydantic import ValidationError
from streamlit.delta_generator import DeltaGenerator

import testgen.ui.services.database_service as db
from testgen.commands.run_profiling_bridge import run_profiling_in_background
from testgen.commands.run_setup_profiling_tools import get_setup_profiling_tools_queries
from testgen.common.database.database_service import empty_cache
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import connection_service, table_group_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.connections.forms import BaseConnectionForm
from testgen.ui.views.connections.models import ConnectionStatus
from testgen.ui.views.table_groups import TableGroupForm

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
        has_table_groups = (
            len(connection_service.get_table_group_names_by_connection([connection["connection_id"]]) or []) > 0
        )

        testgen.page_header(
            "Connection",
            "https://docs.datakitchen.io/article/dataops-testgen-help/connect-your-database",
        )

        testgen.whitespace(0.3)
        _, actions_column = st.columns([.1, .9])
        testgen.whitespace(0.3)
        testgen.flex_row_end(actions_column)

        with st.container(border=True):
            self.show_connection_form(connection.to_dict(), "edit", project_code)

        if has_table_groups:
            with actions_column:
                testgen.link(
                    label="Manage Table Groups",
                    href="connections:table-groups",
                    params={"connection_id": str(connection["connection_id"])},
                    right_icon="chevron_right",
                    underline=False,
                    height=40,
                    style="margin-left: auto; border-radius: 4px;"
                        " border: var(--button-stroked-border); padding: 8px 8px 8px 16px; color: var(--primary-color)",
                )
        else:
            with actions_column:
                testgen.button(
                    type_="stroked",
                    color="primary",
                    icon="table_view",
                    label="Setup Table Groups",
                    style="background: white;",
                    width=200,
                    on_click=lambda: self.setup_data_configuration(project_code, connection.to_dict()),
                )

    def show_connection_form(self, selected_connection: dict, _mode: str, project_code) -> None:
        connection = selected_connection or {}
        connection_id = connection.get("connection_id", None)
        sql_flavor = connection.get("sql_flavor", "postgresql")
        data = {}

        try:
            FlavorForm = BaseConnectionForm.for_flavor(sql_flavor)
            if connection:
                connection["password"] = connection["password"] or ""
                FlavorForm = BaseConnectionForm.for_flavor(sql_flavor)

            form_kwargs = connection or {"sql_flavor": sql_flavor}
            form = FlavorForm(**form_kwargs)

            sql_flavor = form.get_field_value("sql_flavor", latest=True) or sql_flavor
            if form.sql_flavor != sql_flavor:
                form = BaseConnectionForm.for_flavor(sql_flavor)(sql_flavor=sql_flavor)

            form_errors_container = st.empty()
            data = sp.pydantic_input(
                key=f"connection_form:{connection_id or 'new'}",
                model=form,  # type: ignore
            )
            data.update({
                "project_code": project_code,
            })
            if "private_key" not in data:
                data.update({
                    "connect_by_key": False,
                    "private_key_passphrase": None,
                    "private_key": None,
                })

            try:
                FlavorForm.model_validate(data)
            except ValidationError as error:
                form_errors_container.warning("\n".join([
                    f"- {field_label}: {err['msg']}" for err in error.errors()
                    if (field_label := FlavorForm.get_field_label(str(err["loc"][0])))
                ]))
        except Exception:
            LOG.exception("unexpected form validation error")
            st.error("Unexpected error displaying the form. Try again")

        test_button_column, config_qc_column, _, save_button_column = st.columns([.2, .2, .4, .2])
        is_submitted, set_submitted = temp_value(f"connection_form-{connection_id or 'new'}:submit")
        get_connection_status, set_connection_status = temp_value(
            f"connection_form-{connection_id or 'new'}:test_conn"
        )

        with save_button_column:
            testgen.button(
                type_="flat",
                label="Save",
                key=f"connection_form:{connection_id or 'new'}:submit",
                on_click=lambda: set_submitted(True),
            )

        with test_button_column:
            testgen.button(
                type_="stroked",
                color="basic",
                label="Test Connection",
                key=f"connection_form:{connection_id or 'new'}:test",
                on_click=lambda: set_connection_status(self.test_connection(data)),
            )

        with config_qc_column:
            testgen.button(
                type_="stroked",
                color="basic",
                label="Configure QC Utility Schema",
                key=f"connection_form:{connection_id or 'new'}:config-qc-schema",
                tooltip="Creates the required Utility schema and related functions in the target database",
                on_click=lambda: self.create_qc_schema_dialog(connection)
            )

        if (connection_status := get_connection_status()):
            single_element_container = st.empty()
            single_element_container.info("Connecting ...")

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

            connection_status = None
        else:
            # This is needed to fix a strange bug in Streamlit when using dialog + input fields + button
            # If an input field is changed and the button is clicked immediately (without unfocusing the input first),
            # two fragment reruns happen successively, one for unfocusing the input and the other for clicking the button
            # Some or all (it seems random) of the input fields disappear when this happens
            time.sleep(0.1)

        if is_submitted():
            if not data.get("password") and not data.get("connect_by_key"):
                st.error("Enter a valid password.")
            else:
                if data.get("private_key"):
                    data["private_key"] = data["private_key"].getvalue().decode("utf-8")

                connection_service.edit_connection(data)
                st.success("Changes have been saved successfully.")
                time.sleep(1)
                st.rerun()

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

    @st.dialog(title="Data Configuration Setup")
    def setup_data_configuration(self, project_code: str, connection: dict) -> None:
        will_run_profiling = st.session_state.get("connection_form-new:run-profiling-toggle", True)
        testgen.wizard(
            key="connections:setup-wizard",
            steps=[
                testgen.WizardStep(
                    title="Create a Table Group",
                    body=partial(self.create_table_group_step, project_code, connection),
                ),
                testgen.WizardStep(
                    title="Run Profiling",
                    body=self.run_data_profiling_step,
                ),
            ],
            on_complete=self.execute_setup,
            complete_label="Save & Run Profiling" if will_run_profiling else "Finish Setup",
            navigate_to=st.session_state.pop("setup_data_config:navigate-to", None),
            navigate_to_args=st.session_state.pop("setup_data_config:navigate-to-args", {}),
        )

    def create_table_group_step(self, project_code: str, connection: dict) -> tuple[dict | None, bool]:
        is_valid: bool = True
        data: dict = {}

        try:
            form = TableGroupForm.model_construct()
            form_errors_container = st.empty()
            data = sp.pydantic_input(key="table_form:new", model=form)  # type: ignore

            try:
                TableGroupForm.model_validate(data)
                form_errors_container.empty()
                data.update({"project_code": project_code, "connection_id": connection["connection_id"]})
            except ValidationError as error:
                form_errors_container.warning("\n".join([
                    f"- {field_label}: {err['msg']}" for err in error.errors()
                    if (field_label := TableGroupForm.get_field_label(str(err["loc"][0])))
                ]))
                is_valid = False
        except Exception:
            LOG.exception("unexpected form validation error")
            st.error("Unexpected error displaying the form. Try again")
            is_valid = False

        return data, is_valid

    def run_data_profiling_step(self, step_0: testgen.WizardStep | None = None) -> tuple[bool, bool]:
        if not step_0 or not step_0.results:
            st.error("A table group is required to complete this step.")
            return False, False

        run_profiling = True
        profiling_message = "Profiling will be performed in a background process."
        table_group = step_0.results

        with st.container():
            run_profiling = st.checkbox(
                label=f"Execute profiling for the table group **{table_group['table_groups_name']}**?",
                key="connection_form-new:run-profiling-toggle",
                value=True,
            )
            if not run_profiling:
                profiling_message = (
                    "Profiling will be skipped. You can run this step later from the Profiling Runs page."
                )
            st.markdown(f":material/info: _{profiling_message}_")

        return run_profiling, True

    def execute_setup(
        self,
        container: DeltaGenerator,
        step_0: testgen.WizardStep[dict],
        step_1: testgen.WizardStep[bool],
    ) -> bool:
        table_group = step_0.results
        table_group_name: str = table_group["table_groups_name"]
        should_run_profiling: bool = step_1.results

        with container.container():
            status_container = st.empty()

            try:
                status_container.info(f"Creating table group **{table_group_name.strip()}**.")
                table_group_id = table_group_service.add(table_group)
                TableGroupForm.model_construct().reset_cache()
            except Exception as err:
                status_container.error(f"Error creating table group: {err!s}.")

            if should_run_profiling:
                try:
                    status_container.info("Starting profiling run ...")
                    run_profiling_in_background(table_group_id)
                    status_container.success(f"Profiling run started for table group **{table_group_name.strip()}**.")
                except Exception as err:
                    status_container.error(f"Profiling run encountered errors: {err!s}.")

                _, link_column = st.columns([.7, .3])
                with link_column:
                    testgen.button(
                        type_="stroked",
                        color="primary",
                        label="Go to Profiling Runs",
                        icon="chevron_right",
                        key="setup_data_config:keys:go-to-runs",
                        on_click=lambda: (
                            st.session_state.__setattr__("setup_data_config:navigate-to", "profiling-runs")
                            or st.session_state.__setattr__("setup_data_config:navigate-to-args", {
                                "table_group": table_group_id
                            })
                        ),
                    )

        return not should_run_profiling
