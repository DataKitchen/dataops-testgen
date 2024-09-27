import time
import typing
from functools import partial

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

import testgen.ui.services.authentication_service as authentication_service
import testgen.ui.services.connection_service as connection_service
import testgen.ui.services.form_service as fm
import testgen.ui.services.table_group_service as table_group_service
from testgen.commands.run_profiling_bridge import run_profiling_in_background
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.services import project_service
from testgen.ui.services.string_service import empty_if_null
from testgen.ui.session import session


class TableGroupsPage(Page):
    path = "connections:table-groups"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: authentication_service.current_user_has_admin_role(),
        lambda: "connection_id" in session.current_page_args or "connections",
    ]

    def render(self, connection_id: str, **_kwargs) -> None:
        connection = connection_service.get_by_id(connection_id, hide_passwords=False)
        if not connection:
            self.router.navigate_with_warning(
                f"Connection with ID '{connection_id}' does not exist. Redirecting to list of Connections ...",
                "connections",
            )

        project_code = connection["project_code"]
        project_service.set_current_project(project_code)

        testgen.page_header(
            "Table Groups",
            "https://docs.datakitchen.io/article/dataops-testgen-help/create-a-table-group",
            breadcrumbs=[
                { "label": "Connections", "path": "connections", "params": { "project_code": project_code } },
                { "label": connection["connection_name"] },
            ],
        )

        _, actions_column = st.columns([.1, .9], vertical_alignment="bottom")
        testgen.flex_row_end(actions_column)

        df = table_group_service.get_by_connection(project_code, connection_id)

        for _, table_group in df.iterrows():
            with testgen.card(title=table_group["table_groups_name"]) as table_group_card:
                with table_group_card.actions:
                    testgen.button(
                        type_="icon",
                        icon="edit",
                        tooltip="Edit table group",
                        tooltip_position="right",
                        on_click=partial(self.edit_table_group_dialog, project_code, connection, table_group),
                        key=f"tablegroups:keys:edit:{table_group['id']}",
                    )
                    testgen.button(
                        type_="icon",
                        icon="delete",
                        tooltip="Delete table group",
                        tooltip_position="right",
                        on_click=partial(self.delete_table_group_dialog, table_group),
                        key=f"tablegroups:keys:delete:{table_group['id']}",
                    )

                main_section, actions_section = st.columns([.8, .2])

                with main_section:
                    testgen.link(
                        label="Test Suites",
                        href="test-suites",
                        params={"table_group_id": table_group["id"]},
                        right_icon="chevron_right",
                        key=f"tablegroups:keys:go-to-tsuites:{table_group['id']}",
                    )

                    col1, col2, col3 = st.columns([1/3] * 3, vertical_alignment="bottom")
                    col4, col5, col6 = st.columns([1/3] * 3, vertical_alignment="bottom")

                    with col1:
                        testgen.no_flex_gap()
                        testgen.caption("DB Schema")
                        st.markdown(table_group["table_group_schema"] or "--")
                    with col2:
                        testgen.no_flex_gap()
                        testgen.caption("Tables to Include Mask")
                        st.markdown(table_group["profiling_include_mask"] or "--")
                    with col3:
                        testgen.no_flex_gap()
                        testgen.caption("Tables to Exclude Mask")
                        st.markdown(table_group["profiling_exclude_mask"] or "--")
                    with col4:
                        testgen.no_flex_gap()
                        testgen.caption("Explicit Table List")
                        st.markdown(table_group["profiling_table_set"] or "--")
                    with col5:
                        testgen.no_flex_gap()
                        testgen.caption("Uses Record Sampling")
                        st.markdown(table_group["profile_use_sampling"] or "N")
                    with col6:
                        testgen.no_flex_gap()
                        testgen.caption("Min Profiling Age (Days)")
                        st.markdown(table_group["profiling_delay_days"] or "0")

                with actions_section:
                    testgen.button(
                        type_="stroked",
                        label="Run Profiling",
                        on_click=partial(run_profiling_dialog, table_group),
                        key=f"tablegroups:keys:runprofiling:{table_group['id']}",
                    )

        actions_column.button(
            ":material/add: Add Table Group",
            help="Add a new Table Group",
            on_click=partial(self.add_table_group_dialog, project_code, connection)
        )

    @st.dialog(title="Add Table Group")
    def add_table_group_dialog(self, project_code, connection):
        show_table_group_form("add", project_code, connection)

    @st.dialog(title="Edit Table Group")
    def edit_table_group_dialog(self, project_code: str, connection: dict, table_group: pd.Series):
        show_table_group_form("edit", project_code, connection, table_group)

    @st.dialog(title="Delete Table Group")
    def delete_table_group_dialog(self, table_group: pd.Series):
        table_group_name = table_group["table_groups_name"]
        can_be_deleted = table_group_service.cascade_delete([table_group_name], dry_run=True)

        fm.render_html_list(
            table_group,
            [
                "id",
                "table_groups_name",
                "table_group_schema",
            ],
            "Table Group Information",
            int_data_width=700,
        )

        if not can_be_deleted:
            st.markdown(
                ":orange[This Table Group has related data, which may include profiling, test definitions and test results. If you proceed, all related data will be permanently deleted.<br/>Are you sure you want to proceed?]",
                unsafe_allow_html=True,
            )
            accept_cascade_delete = st.toggle("I accept deletion of this Table Group and all related TestGen data.")

        with st.form("Delete Table Group", clear_on_submit=True):
            disable_delete_button = authentication_service.current_user_has_read_role() or (
                not can_be_deleted and not accept_cascade_delete
            )
            delete = st.form_submit_button("Delete", disabled=disable_delete_button, type="primary")

            if delete:
                if table_group_service.are_table_groups_in_use([table_group_name]):
                    st.error("This Table Group is in use by a running process and cannot be deleted.")
                else:
                    table_group_service.cascade_delete([table_group_name])
                    success_message = f"Table Group {table_group_name} has been deleted. "
                    st.success(success_message)
                    time.sleep(1)
                    st.rerun()


@st.dialog(title="Run Profiling")
def run_profiling_dialog(table_group: pd.Series) -> None:
    table_group_id = table_group["id"]

    with st.container():
        st.markdown(
            f"Execute profiling for the Table Group :green[{table_group['table_groups_name']}]?"
            " Profiling will be performed in a background process"
        )

    if testgen.expander_toggle(expand_label="Show CLI command", key="test_suite:keys:run-tests-show-cli"):
        st.code(f"testgen run-profile --table-group-id {table_group_id}", language="shellSession")

    button_container = st.empty()
    status_container = st.empty()

    with button_container:
        _, button_column = st.columns([.85, .15])
        with button_column:
            profile_button = st.button("Start", use_container_width=True)

    if profile_button:
        button_container.empty()

        status_container.info("Executing Profiling...")

        try:
            run_profiling_in_background(table_group_id)
        except Exception as e:
            status_container.empty()
            status_container.error(f"Process started with errors: {e!s}.")

        status_container.empty()
        status_container.success(
            "Process has successfully started. Check 'Data Profiling' item in the menu to see the progress."
        )


def show_table_group_form(mode, project_code: str, connection: dict, table_group: pd.Series | None = None):
    connection_id = connection["connection_id"]
    table_groups_settings_tab, table_groups_preview_tab = st.tabs(["Table Group Settings", "Test"])

    table_group_id = None
    table_groups_name = ""
    table_group_schema = ""
    profiling_table_set = ""
    profiling_include_mask = "%"
    profiling_exclude_mask = "tmp%"
    profile_id_column_mask = "%_id"
    profile_sk_column_mask = "%_sk"
    profile_use_sampling = False
    profile_sample_percent = 30
    profile_sample_min_count = 15000
    profiling_delay_days = 0

    with table_groups_settings_tab:
        selected_table_group = table_group if mode == "edit" else None

        if selected_table_group is not None:
            # establish default values
            table_group_id = selected_table_group["id"]
            table_groups_name = selected_table_group["table_groups_name"]
            table_group_schema = selected_table_group["table_group_schema"]
            profiling_table_set = selected_table_group["profiling_table_set"]
            profiling_include_mask = selected_table_group["profiling_include_mask"]
            profiling_exclude_mask = selected_table_group["profiling_exclude_mask"]
            profile_id_column_mask = selected_table_group["profile_id_column_mask"]
            profile_sk_column_mask = selected_table_group["profile_sk_column_mask"]
            profile_use_sampling = selected_table_group["profile_use_sampling"] == "Y"
            profile_sample_percent = int(selected_table_group["profile_sample_percent"])
            profile_sample_min_count = int(selected_table_group["profile_sample_min_count"])
            profiling_delay_days = int(selected_table_group["profiling_delay_days"])

        left_column, right_column = st.columns([0.50, 0.50])

        profile_sampling_expander = st.expander("Sampling Parameters", expanded=False)
        with profile_sampling_expander:
            expander_left_column, expander_right_column = st.columns([0.50, 0.50])

        provenance_expander = st.expander("Data Provenance (Optional)", expanded=False)
        with provenance_expander:
            provenance_left_column, provenance_right_column = st.columns([0.50, 0.50])

        with st.form("Table Group Add / Edit", clear_on_submit=True, border=False):
            entity = {
                "id": table_group_id,
                "project_code": project_code,
                "connection_id": connection["connection_id"],
                "table_groups_name": left_column.text_input(
                    label="Name",
                    max_chars=40,
                    value=table_groups_name,
                    help="A unique name to describe the table group",
                ),
                "profiling_include_mask": left_column.text_input(
                    label="Tables to Include Mask",
                    max_chars=40,
                    value=profiling_include_mask,
                    help="A SQL filter supported by your database's LIKE operator for table names to include",
                ),
                "profiling_exclude_mask": left_column.text_input(
                    label="Tables to Exclude Mask",
                    max_chars=40,
                    value=profiling_exclude_mask,
                    help="A SQL filter supported by your database's LIKE operator for table names to exclude",
                ),
                "profiling_table_set": left_column.text_input(
                    label="Explicit Table List",
                    max_chars=2000,
                    value=profiling_table_set,
                    help="A list of specific table names to include, separated by commas",
                ),
                "table_group_schema": right_column.text_input(
                    label="Schema",
                    max_chars=40,
                    value=table_group_schema,
                    help="The database schema containing the tables in the Table Group",
                ),
                "profile_id_column_mask": right_column.text_input(
                    label="Profiling ID column mask",
                    max_chars=40,
                    value=profile_id_column_mask,
                    help="A SQL filter supported by your database's LIKE operator representing ID columns (optional)",
                ),
                "profile_sk_column_mask": right_column.text_input(
                    label="Profiling Surrogate Key column mask",
                    max_chars=40,
                    value=profile_sk_column_mask,
                    help="A SQL filter supported by your database's LIKE operator representing surrogate key columns (optional)",
                ),
                "profiling_delay_days": right_column.number_input(
                    label="Min Profiling Age, Days",
                    min_value=0,
                    max_value=999,
                    value=profiling_delay_days,
                    help="The number of days to wait before new profiling will be available to generate tests",
                ),
                "profile_use_sampling": left_column.toggle(
                    "Use profile sampling",
                    value=profile_use_sampling,
                    help="Toggle on to base profiling on a sample of records instead of the full table",
                ),
                "profile_sample_percent": str(
                    expander_left_column.number_input(
                        label="Sample percent",
                        min_value=1,
                        max_value=100,
                        value=profile_sample_percent,
                        help="Percent of records to include in the sample, unless the calculated count falls below the specified minimum.",
                    )
                ),
                "profile_sample_min_count": expander_right_column.number_input(
                    label="Min Sample Record Count",
                    min_value=1,
                    max_value=1000000,
                    value=profile_sample_min_count,
                    help="The minimum number of records to be included in any sample (if available)",
                ),
                "data_source": provenance_left_column.text_input(
                    label="Data Source",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["data_source"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Original source of all tables in this dataset. This can be overridden at the table level. (Optional)",
                ),
                "source_system": provenance_left_column.text_input(
                    label="System of Origin",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["source_system"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Enterprise system source for all tables in this dataset. "
                            "This can be overridden at the table level. (Optional)",
                ),
                "business_domain": provenance_left_column.text_input(
                    label="Business Domain",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["business_domain"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Business division responsible for all tables in this dataset. "
                            "e.g. Finance, Sales, Manufacturing. (Optional)",
                ),
                "data_location": provenance_left_column.text_input(
                    label="Location",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["data_location"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Physical or virtual location of all tables in this dataset. "
                            "e.g. Headquarters, Cloud, etc. (Optional)",
                ),
                "transform_level": provenance_right_column.text_input(
                    label="Transform Level",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["transform_level"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Data warehouse processing layer. "
                            "Indicates the processing stage: e.g. Raw, Conformed, Processed, Reporting. (Optional)",
                ),
                "source_process": provenance_right_column.text_input(
                    label="Source Process",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["source_process"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="The process, program or data flow that produced this data. (Optional)",
                ),
                "stakeholder_group": provenance_right_column.text_input(
                    label="Stakeholder Group",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["stakeholder_group"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Designator for data owners or stakeholders who are responsible for this data. (Optional)",
                ),
            }

            _, button_column = st.columns([.85, .15])
            with button_column:
                submit = st.form_submit_button(
                    "Save" if mode == "edit" else "Add",
                    use_container_width=True,
                    disabled=authentication_service.current_user_has_read_role(),
                )

            if submit:
                if not entity["table_groups_name"]:
                    st.error("'Name' is required. ")
                    return

                try:
                    if mode == "edit":
                        table_group_service.edit(entity)
                        success_message = "Changes have been saved successfully. "
                    else:
                        table_group_service.add(entity)
                        success_message = "New Table Group added successfully. "
                except IntegrityError:
                    st.error("A Table Group with the same name already exists. ")
                    return
                else:
                    st.success(success_message)
                    time.sleep(1)
                    st.rerun()

        with table_groups_preview_tab:
            if mode == "edit":
                preview_left_column, preview_right_column = st.columns([0.5, 0.5])
                status_preview = preview_right_column.empty()
                preview = preview_left_column.button("Test Table Group")
                if preview:
                    table_group_preview(entity, connection_id, project_code, status_preview)
            else:
                st.write("No preview available while adding a Table Group. Save the configuration first.")


def table_group_preview(entity, connection_id, project_code, status):
    status.empty()
    status.info("Connecting to the Table Group ...")
    try:
        table_group_results, qc_results = table_group_service.test_table_group(entity, connection_id, project_code)
        if len(table_group_results) > 0 and all(qc_results):
            tables = set()
            columns = []
            schemas = set()
            for result in table_group_results:
                schemas.add(result["table_schema"])
                tables.add(result["table_name"])
                columns.append(result["column_name"])

            show_test_results(schemas, tables, columns, qc_results)

            status.empty()
            status.success("Operation has finished successfully.")
        else:
            status.empty()
            status.error("Operation was unsuccessful.")
            error_message = ""
            if len(table_group_results) == 0:
                error_message = "Result is empty."
            if not all(qc_results):
                error_message = f"Error testing the connection to the Table Group. Details: {qc_results}"
            st.text_area("Table Group Error Details", value=error_message)
    except Exception as e:
        status.empty()
        status.error("Error testing the Table Group.")
        error_message = e.args[0]
        st.text_area("Table Group Error Details", value=error_message)


def show_test_results(schemas, tables, columns, qc_results):
    qc_test_results = all(qc_results)
    st.markdown(f"**Utility QC Schema Validity Test**: {':white_check_mark:' if qc_test_results else ':x:'}")

    st.markdown(f"**Schema**: {schemas.pop()}")
    st.markdown(f"**Column Count**: {len(columns)}")

    tables_df = pd.DataFrame({"[tables]": list(tables)})
    fm.render_grid_select(tables_df, ["[tables]"])
