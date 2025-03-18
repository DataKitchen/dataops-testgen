import time
import typing
from functools import partial

import pandas as pd
import streamlit as st
from sqlalchemy.exc import IntegrityError

import testgen.ui.services.connection_service as connection_service
import testgen.ui.services.form_service as fm
import testgen.ui.services.table_group_service as table_group_service
from testgen.common.models import with_database_session
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.services import project_service, user_session_service
from testgen.ui.services.string_service import empty_if_null
from testgen.ui.session import session
from testgen.ui.views.dialogs.run_profiling_dialog import run_profiling_dialog


class TableGroupsPage(Page):
    path = "connections:table-groups"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "connection_id" in session.current_page_args or "connections",
    ]

    def render(self, connection_id: str, **_kwargs) -> None:
        connection = connection_service.get_by_id(connection_id, hide_passwords=False)
        if not connection:
            return self.router.navigate_with_warning(
                f"Connection with ID '{connection_id}' does not exist. Redirecting to list of Connections ...",
                "connections",
            )

        project_code = connection["project_code"]
        project_service.set_current_project(project_code)
        user_can_edit = user_session_service.user_can_edit()

        testgen.page_header(
            "Table Groups",
            "create-a-table-group",
            breadcrumbs=[  # type: ignore
                { "label": "Connections", "path": "connections", "params": { "project_code": project_code } },
                { "label": connection["connection_name"] },
            ],
        )

        df = table_group_service.get_by_connection(project_code, connection_id)

        if df.empty:
            testgen.whitespace(3)
            testgen.empty_state(
                label="No table groups yet",
                icon="table_view",
                message=testgen.EmptyStateMessage.TableGroup,
                action_label="Add Table Group",
                action_disabled=not user_can_edit,
                button_onclick=partial(self.add_table_group_dialog, project_code, connection),
            )
            return

        testgen.whitespace(0.3)
        _, actions_column = st.columns([.1, .9], vertical_alignment="bottom")
        testgen.flex_row_end(actions_column)

        if user_can_edit:
            actions_column.button(
                ":material/add: Add Table Group",
                on_click=partial(self.add_table_group_dialog, project_code, connection)
            )

        for _, table_group in df.iterrows():
            with testgen.card(title=table_group["table_groups_name"]) as table_group_card:
                if user_can_edit:
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

                if user_can_edit:
                    with actions_section:
                        testgen.button(
                            type_="stroked",
                            label="Run Profiling",
                            on_click=partial(run_profiling_dialog, project_code, table_group),
                            key=f"tablegroups:keys:runprofiling:{table_group['id']}",
                        )

    @st.dialog(title="Add Table Group")
    @with_database_session
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

        with st.form("Delete Table Group", clear_on_submit=True, border=False):
            _, button_column = st.columns([.85, .15])
            with button_column:
                delete = st.form_submit_button(
                    "Delete",
                    disabled=not can_be_deleted and not accept_cascade_delete,
                    type="primary",
                    use_container_width=True,
                )

            if delete:
                if table_group_service.are_table_groups_in_use([table_group_name]):
                    st.error("This Table Group is in use by a running process and cannot be deleted.")
                else:
                    table_group_service.cascade_delete([table_group_name])
                    success_message = f"Table Group {table_group_name} has been deleted. "
                    st.success(success_message)
                    time.sleep(1)
                    st.rerun()


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
    profile_flag_cdes = True

    with table_groups_settings_tab:
        selected_table_group = table_group if mode == "edit" else None

        if selected_table_group is not None:
            # establish default values
            table_group_id = selected_table_group["id"]
            table_groups_name = selected_table_group["table_groups_name"]
            table_group_schema = selected_table_group["table_group_schema"]
            profiling_table_set = selected_table_group["profiling_table_set"] or ""
            profiling_include_mask = selected_table_group["profiling_include_mask"]
            profiling_exclude_mask = selected_table_group["profiling_exclude_mask"]
            profile_id_column_mask = selected_table_group["profile_id_column_mask"]
            profile_sk_column_mask = selected_table_group["profile_sk_column_mask"]
            profile_use_sampling = selected_table_group["profile_use_sampling"] == "Y"
            profile_sample_percent = int(selected_table_group["profile_sample_percent"])
            profile_sample_min_count = int(selected_table_group["profile_sample_min_count"])
            profiling_delay_days = int(selected_table_group["profiling_delay_days"])
            profile_flag_cdes = selected_table_group["profile_flag_cdes"]

        left_column, right_column = st.columns([0.50, 0.50])

        profile_sampling_expander = st.expander("Sampling Parameters", expanded=False)
        with profile_sampling_expander:
            expander_left_column, expander_right_column = st.columns([0.50, 0.50])

        table_group_tags_expander = st.expander("Table Group Tags", expanded=False)
        with table_group_tags_expander:
            full_width_column = st.container()
            tags_left_column, tags_right_column = st.columns([0.5, 0.5], vertical_alignment="bottom")

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
                "profile_flag_cdes": left_column.checkbox(
                    "Detect critical data elements (CDEs) during profiling",
                    value=profile_flag_cdes,
                ),
                "add_scorecard_definition": right_column.checkbox(
                    "Add scorecard for table group",
                    value=True,
                    help="Add a new scorecard to the Quality Dashboard upon creation of this table group",
                ) if mode != "edit" else None,
                "profile_use_sampling": left_column.checkbox(
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
                "description": full_width_column.text_input(
                    label="Description",
                    max_chars=1000,
                    value=empty_if_null(selected_table_group["description"])
                    if mode == "edit" and selected_table_group is not None else "",
                ),
                "data_source": tags_left_column.text_input(
                    label="Data Source",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["data_source"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Original source of the dataset",
                ),
                "source_system": tags_right_column.text_input(
                    label="Source System",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["source_system"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Enterprise system source for the dataset",
                ),
                "source_process": tags_left_column.text_input(
                    label="Source Process",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["source_process"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Process, program, or data flow that produced the dataset",
                ),
                "data_location": tags_right_column.text_input(
                    label="Data Location",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["data_location"])
                    if mode == "edit" and selected_table_group is not None else "",
                    help="Physical or virtual location of the dataset, e.g., Headquarters, Cloud",
                ),
                "business_domain": tags_left_column.text_input(
                    label="Business Domain",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["business_domain"])
                    if mode == "edit" and selected_table_group is not None else "",
                    help="Business division responsible for the dataset, e.g., Finance, Sales, Manufacturing",
                ),
                "stakeholder_group": tags_right_column.text_input(
                    label="Stakeholder Group",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["stakeholder_group"])
                    if mode == "edit" and selected_table_group is not None else "",
                    help="Data owners or stakeholders responsible for the dataset",
                ),
                "transform_level": tags_left_column.text_input(
                    label="Transform Level",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["transform_level"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Data warehouse processing stage, e.g., Raw, Conformed, Processed, Reporting, or Medallion level (bronze, silver, gold)",
                ),
                "data_product": tags_right_column.text_input(
                    label="Data Product",
                    max_chars=40,
                    value=empty_if_null(selected_table_group["data_product"])
                        if mode == "edit" and selected_table_group is not None else "",
                    help="Data domain that comprises the dataset"
                ),
            }

            _, button_column = st.columns([.85, .15])
            with button_column:
                submit = st.form_submit_button(
                    "Save" if mode == "edit" else "Add",
                    use_container_width=True,
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
                        success_message = "New table group added successfully. "
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
        table_group_results = table_group_service.test_table_group(entity, connection_id, project_code)
        if len(table_group_results) > 0:
            tables = set()
            columns = []
            schemas = set()
            for result in table_group_results:
                schemas.add(result["table_schema"])
                tables.add(result["table_name"])
                columns.append(result["column_name"])

            show_test_results(schemas, tables, columns)

            status.empty()
            status.success("Operation has finished successfully.")
        else:
            status.empty()
            status.error("Operation was unsuccessful.")
            error_message = ""
            if len(table_group_results) == 0:
                error_message = "Result is empty."
            st.text_area("Table Group Error Details", value=error_message)
    except Exception as e:
        status.empty()
        status.error("Error testing the Table Group.")
        error_message = e.args[0]
        st.text_area("Table Group Error Details", value=error_message)


def show_test_results(schemas, tables, columns):
    st.markdown(f"**Schema**: {schemas.pop()}")
    st.markdown(f"**Column Count**: {len(columns)}")

    tables_df = pd.DataFrame({"[tables]": list(tables)})
    fm.render_grid_select(tables_df, ["[tables]"])
