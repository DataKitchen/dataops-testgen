import logging
import time
import typing
from functools import partial

import streamlit as st
import streamlit_pydantic as sp
from pydantic import ValidationError
from streamlit.delta_generator import DeltaGenerator

import testgen.ui.services.database_service as db
from testgen.commands.run_profiling_bridge import run_profiling_in_background
from testgen.common.database.database_service import empty_cache
from testgen.common.models import with_database_session
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import connection_service, table_group_service, user_session_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.connections.forms import BaseConnectionForm
from testgen.ui.views.connections.models import ConnectionStatus
from testgen.ui.views.table_groups import TableGroupForm

LOG = logging.getLogger("testgen")
PAGE_TITLE = "Connection"


class ConnectionsPage(Page):
    path = "connections"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
    ]
    menu_item = MenuItem(
        icon="database",
        label=PAGE_TITLE,
        section="Data Configuration",
        order=0,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
    )

    def render(self, project_code: str, **_kwargs) -> None:
        dataframe = connection_service.get_connections(project_code)
        connection = dataframe.iloc[0]
        has_table_groups = (
            len(connection_service.get_table_group_names_by_connection([connection["connection_id"]]) or []) > 0
        )

        testgen.page_header(
            PAGE_TITLE,
            "connect-your-database",
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
                    style="margin-left: auto; border-radius: 4px; background: var(--dk-card-background);"
                        " border: var(--button-stroked-border); padding: 8px 8px 8px 16px; color: var(--primary-color)",
                )
        else:
            user_can_edit = user_session_service.user_can_edit()
            with actions_column:
                testgen.button(
                    type_="stroked",
                    color="primary",
                    icon="table_view",
                    label="Setup Table Groups",
                    style="var(--dk-card-background)",
                    width=200,
                    disabled=not user_can_edit,
                    tooltip=None if user_can_edit else user_session_service.DISABLED_ACTION_TEXT,
                    on_click=lambda: self.setup_data_configuration(project_code, connection.to_dict()),
                )

    def show_connection_form(self, selected_connection: dict, _mode: str, project_code) -> None:
        connection = selected_connection or {}
        connection_id = connection.get("connection_id", 1)
        connection_name = connection.get("connection_name", "default")
        sql_flavor = connection.get("sql_flavor", "postgresql")
        data = {}

        try:
            FlavorForm = BaseConnectionForm.for_flavor(sql_flavor)
            if connection:
                connection["password"] = connection["password"] or ""

            form_kwargs = connection or {"sql_flavor": sql_flavor, "connection_id": connection_id, "connection_name": connection_name}
            form = FlavorForm(**form_kwargs)

            BaseConnectionForm.set_default_port(sql_flavor, form)

            sql_flavor = form.get_field_value("sql_flavor", latest=True) or sql_flavor
            if form.sql_flavor != sql_flavor:
                form = BaseConnectionForm.for_flavor(sql_flavor)(sql_flavor=sql_flavor, connection_id=connection_id)

            form.disable("connection_name")

            form_errors_container = st.empty()
            data = sp.pydantic_input(
                key=f"connection_form:{connection_id}",
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

            data.setdefault("http_path", "")

            try:
                FlavorForm(**data)
            except ValidationError as error:
                form_errors_container.warning("\n".join([
                    f"- {field_label}: {err['msg']}" for err in error.errors()
                    if (field_label := FlavorForm.get_field_label(str(err["loc"][0])))
                ]))
        except Exception:
            LOG.exception("unexpected form validation error")
            st.error("Unexpected error displaying the form. Try again")

        test_button_column, _, save_button_column = st.columns([.2, .6, .2])
        is_submitted, set_submitted = temp_value(f"connection_form-{connection_id}:submit")
        is_connecting, set_connecting = temp_value(
            f"connection_form-{connection_id}:test_conn"
        )

        if user_session_service.user_is_admin():
            with save_button_column:
                testgen.button(
                    type_="flat",
                    label="Save",
                    key=f"connection_form:{connection_id}:submit",
                    on_click=lambda: set_submitted(True),
                )

            with test_button_column:
                testgen.button(
                    type_="stroked",
                    color="basic",
                    label="Test Connection",
                    key=f"connection_form:{connection_id}:test",
                    on_click=lambda: set_connecting(True),
                )

        if is_connecting():
            single_element_container = st.empty()
            single_element_container.info("Connecting ...")
            connection_status = self.test_connection(data)

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
                connection["http_path"],
                sql_query,
            )
            connection_successful = len(results) == 1 and results[0][0] == 1

            if not connection_successful:
                return ConnectionStatus(message="Error completing a query to the database server.", successful=False)
            return ConnectionStatus(message="The connection was successful.", successful=True)
        except Exception as error:
            return ConnectionStatus(message="Error attempting the connection.", details=error.args[0], successful=False)

    @st.dialog(title="Data Configuration Setup")
    @with_database_session
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
            form = TableGroupForm.construct()
            form_errors_container = st.empty()
            data = sp.pydantic_input(key="table_form:new", model=form)  # type: ignore

            try:
                TableGroupForm(**data)
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
                TableGroupForm.construct().reset_cache()
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
