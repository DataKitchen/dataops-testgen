import time
import typing

import pandas as pd
import streamlit as st

import testgen.ui.services.authentication_service as authentication_service
import testgen.ui.services.connection_service as connection_service
import testgen.ui.services.form_service as fm
import testgen.ui.services.table_group_service as table_group_service
import testgen.ui.services.toolbar_service as tb
from testgen.commands.run_profiling_bridge import run_profiling_in_background
from testgen.ui.navigation.page import Page
from testgen.ui.services.string_service import empty_if_null
from testgen.ui.session import session


class TableGroupsPage(Page):
    path = "connections:table-groups"
    can_activate: typing.ClassVar = [
        lambda: authentication_service.current_user_has_admin_role() or "overview",
        lambda: session.authentication_status,
    ]

    def render(self, connection_id: int | None = None) -> None:
        fm.render_page_header(
            "Table Groups",
            "https://docs.datakitchen.io/article/dataops-testgen-help/create-a-table-group",
            lst_breadcrumbs=[
                {"label": "Overview", "path": "overview"},
                {"label": "Connections", "path": "connections"},
                {"label": "Table Groups", "path": None},
            ],
        )

        # Get page parameters from session
        project_code = st.session_state["project"]
        connection = (
            connection_service.get_by_id(connection_id, hide_passwords=False)
            if connection_id
            else st.session_state["connection"]
        )
        connection_id = connection["connection_id"]

        tool_bar = tb.ToolBar(1, 5, 0, None)

        with tool_bar.long_slots[0]:
            st.selectbox("Connection", [connection["connection_name"]], disabled=True)

        df = table_group_service.get_by_connection(project_code, connection_id)

        show_columns = [
            "table_groups_name",
            "table_group_schema",
            "profiling_include_mask",
            "profiling_exclude_mask",
            "profiling_table_set",
            "profile_use_sampling",
            "profiling_delay_days",
        ]

        show_column_headers = [
            "Table Groups Name",
            "DB Schema",
            "Tables to Include Mask",
            "Tables to Exclude Mask",
            "Explicit Table List",
            "Uses Record Sampling",
            "Min Profiling Age (Days)",
        ]

        selected = fm.render_grid_select(df, show_columns, show_column_headers=show_column_headers)

        if tool_bar.short_slots[1].button(
            "➕ Add", help="Add a new Table Group", use_container_width=True  # NOQA RUF001
        ):
            add_table_group_dialog(project_code, connection)

        disable_buttons = selected is None
        if tool_bar.short_slots[2].button(
            "🖊️ Edit", help="Edit the selected Table Group", disabled=disable_buttons, use_container_width=True
        ):
            edit_table_group_dialog(project_code, connection, selected)

        if tool_bar.short_slots[3].button(
            "❌ Delete", help="Delete the selected Table Group", disabled=disable_buttons, use_container_width=True
        ):
            delete_table_group_dialog(selected)

        if tool_bar.short_slots[4].button(
            f":{'gray' if disable_buttons else 'green'}[Test Suites　→]",
            help="Create or edit Test Suites for the selected Table Group",
            disabled=disable_buttons,
            use_container_width=True,
        ):
            st.session_state["table_group"] = selected[0]

            self.router.navigate(
                "connections:test-suites",
                {"connection_id": connection_id, "table_group_id": selected[0]["id"]},
            )

        if not selected:
            st.markdown(":orange[Select a row to see Table Group details.]")
        else:
            show_record_detail(selected[0])


def show_record_detail(selected):
    left_column, right_column = st.columns([0.5, 0.5])

    with left_column:
        fm.render_html_list(
            selected,
            lst_columns=[
                "id",
                "project_code",
                "table_groups_name",
                "table_group_schema",
                "profiling_include_mask",
                "profiling_exclude_mask",
                "profiling_table_set",
                "profile_id_column_mask",
                "profile_sk_column_mask",

                "data_source",
                "source_system",
                "data_location",
                "business_domain",
                "transform_level",
                "source_process",
                "stakeholder_group",

                "profile_use_sampling",
                "profile_sample_percent",
                "profile_sample_min_count",
                "profiling_delay_days",
            ],
            str_section_header="Table Group Information",
            int_data_width=700,
            lst_labels=[
                "id",
                "Project",
                "Table Groups Name",
                "Database Schema",
                "Tables to Include Mask",
                "Tables to Exlude Mask",
                "Explicit Table List",
                "ID Column Mask",
                "Surrogate Key Column Mask",

                "Data Source",
                "Source System",
                "Data Location",
                "Business Domain",
                "Transform Level",
                "Source Process",
                "Stakeholder Group",

                "Uses Record Sampling",
                "Sample Record Percent",
                "Sample Minimum Record Count",
                "Minimum Profiling Age (Days)",
            ],
        )

    with right_column:
        st.write("<br/><br/>", unsafe_allow_html=True)
        _, button_column = st.columns([0.3, 0.7])
        with button_column:
            if st.button("Run Profiling", help="Performs profiling on the Table Group", use_container_width=True):
                run_profiling_dialog(selected)
            if st.button(
                "Show Run Profile CLI Command", help="Shows the run-profile CLI command", use_container_width=True
            ):
                run_profiling_cli_dialog(selected)


@st.dialog(title="Run Profiling")
def run_profiling_dialog(selected_table_group):
    container = st.empty()
    with container:
        st.markdown(
            ":green[Execute Profile for the Table Group (since can take time, it is performed in background)]"
        )

    button_container = st.empty()
    status_container = st.empty()

    with button_container:
        start_process_button_message = "Start"
        profile_button = st.button(start_process_button_message)

    if profile_button:
        button_container.empty()

        table_group_id = selected_table_group["id"]
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


@st.dialog(title="Run Profiling CLI Command")
def run_profiling_cli_dialog(selected_table_group):
    table_group_id = selected_table_group["id"]
    profile_command = f"testgen run-profile --table-group-id {table_group_id}"
    st.code(profile_command, language="shellSession")


@st.dialog(title="Delete Table Group")
def delete_table_group_dialog(selected):
    selected_table_group = selected[0]
    table_group_name = selected_table_group["table_groups_name"]
    can_be_deleted = table_group_service.cascade_delete([table_group_name], dry_run=True)

    fm.render_html_list(
        selected_table_group,
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


def show_table_group_form(mode, project_code, connection, selected=None):
    connection_id = connection["connection_id"]
    table_groups_settings_tab, table_groups_preview_tab = st.tabs(["Table Group Settings", "Test"])

    with table_groups_settings_tab:
        selected_table_group = selected[0] if mode == "edit" else None

        # establish default values
        table_group_id = selected_table_group["id"] if mode == "edit" else None
        table_groups_name = (
            selected_table_group["table_groups_name"]
            if mode == "edit"
            else f'{connection["connection_name"]}_table_group'
        )
        table_group_schema = selected_table_group["table_group_schema"] if mode == "edit" else ""
        profiling_table_set = (
            selected_table_group["profiling_table_set"]
            if mode == "edit" and selected_table_group["profiling_table_set"]
            else ""
        )
        profiling_include_mask = selected_table_group["profiling_include_mask"] if mode == "edit" else "%"
        profiling_exclude_mask = selected_table_group["profiling_exclude_mask"] if mode == "edit" else "tmp%"
        profile_id_column_mask = selected_table_group["profile_id_column_mask"] if mode == "edit" else "%_id"
        profile_sk_column_mask = selected_table_group["profile_sk_column_mask"] if mode == "edit" else "%_sk"
        profile_use_sampling = selected_table_group["profile_use_sampling"] == "Y" if mode == "edit" else False
        profile_sample_percent = int(selected_table_group["profile_sample_percent"]) if mode == "edit" else 30
        profile_sample_min_count = (
            int(selected_table_group["profile_sample_min_count"]) if mode == "edit" else 15000
        )
        profiling_delay_days = int(selected_table_group["profiling_delay_days"]) if mode == "edit" else 0

        left_column, right_column = st.columns([0.50, 0.50])

        profile_sampling_expander = st.expander("Sampling Parameters", expanded=False)
        with profile_sampling_expander:
            expander_left_column, expander_right_column = st.columns([0.50, 0.50])

        provenance_expander = st.expander("Data Provenance (Optional)", expanded=False)
        with provenance_expander:
            provenance_left_column, provenance_right_column = st.columns([0.50, 0.50])

        with st.form("Table Group Add / Edit", clear_on_submit=True):
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
                    value=empty_if_null(selected_table_group["data_source"]) if mode == "edit" else "",
                    help="Original source of all tables in this dataset. This can be overridden at the table level. (Optional)",
                ),
                "source_system": provenance_left_column.text_input(
                    label="System of Origin",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["source_system"]) if mode == "edit" else "",
                    help="Enterprise system source for all tables in this dataset. "
                            "This can be overridden at the table level. (Optional)",
                ),
                "business_domain": provenance_left_column.text_input(
                    label="Business Domain",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["business_domain"]) if mode == "edit" else "",
                    help="Business division responsible for all tables in this dataset. "
                            "e.g. Finance, Sales, Manufacturing. (Optional)",
                ),
                "data_location": provenance_left_column.text_input(
                    label="Location",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["data_location"]) if mode == "edit" else "",
                    help="Physical or virtual location of all tables in this dataset. "
                            "e.g. Headquarters, Cloud, etc. (Optional)",
                ),
                "transform_level": provenance_right_column.text_input(
                    label="Transform Level",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["transform_level"]) if mode == "edit" else "",
                    help="Data warehouse processing layer. "
                            "Indicates the processing stage: e.g. Raw, Conformed, Processed, Reporting. (Optional)",
                ),
                "source_process": provenance_right_column.text_input(
                    label="Source Process",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["source_process"]) if mode == "edit" else "",
                    help="The process, program or data flow that produced this data. (Optional)",
                ),
                "stakeholder_group": provenance_right_column.text_input(
                    label="Stakeholder Group",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["stakeholder_group"]) if mode == "edit" else "",
                    help="Designator for data owners or stakeholders who are responsible for this data. (Optional)",
                ),
            }

            submit_button_text = "Save" if mode == "edit" else "Add"
            submit = st.form_submit_button(
                submit_button_text, disabled=authentication_service.current_user_has_read_role()
            )

            if submit:
                if mode == "edit":
                    table_group_service.edit(entity)
                else:
                    table_group_service.add(entity)
                success_message = (
                    "Changes have been saved successfully. "
                    if mode == "edit"
                    else "New Table Group added successfully. "
                )
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


@st.dialog(title="Add Table Group")
def add_table_group_dialog(project_code, connection):
    show_table_group_form("add", project_code, connection)


@st.dialog(title="Edit Table Group")
def edit_table_group_dialog(project_code, connection, selected):
    show_table_group_form("edit", project_code, connection, selected)
