import json
import typing
from functools import partial

import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
import testgen.ui.services.query_service as dq
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import project_queries
from testgen.ui.session import session
from testgen.ui.views.dialogs.run_profiling_dialog import run_profiling_dialog
from testgen.utils import is_uuid4

PAGE_ICON = "dataset"

class DataHierarchyPage(Page):
    path = "data-hierarchy"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon=PAGE_ICON, label="Data Hierarchy", order=1)

    def render(self, project_code: str | None = None, table_group_id: str | None = None, selected: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            "Data Hierarchy",
        )

        project_code = project_code or session.project

        if render_empty_state(project_code):
            return
        
        group_filter_column, _, loading_column = st.columns([.3, .5, .2], vertical_alignment="center")

        with group_filter_column:
            table_groups_df = get_table_group_options(project_code)
            table_group_id = testgen.select(
                options=table_groups_df,
                value_column="id",
                display_column="table_groups_name",
                default_value=table_group_id,
                required=True,
                label="Table Group",
                bind_to_query="table_group_id",
            )

        with loading_column:
            columns_df = get_table_group_columns(table_group_id)
            selected_item = get_selected_item(selected, table_group_id)
            if not selected_item:
                self.router.set_query_params({ "selected": None })

        if columns_df.empty:
            table_group = table_groups_df.loc[table_groups_df["id"] == table_group_id].iloc[0]
            testgen.empty_state(
                label="No profiling data yet",
                icon=PAGE_ICON,
                message=testgen.EmptyStateMessage.Profiling,
                action_label="Run Profiling",
                button_onclick=partial(run_profiling_dialog, project_code, table_group),
                button_icon="play_arrow",
            )
        else:
            def on_tree_node_select(node_id):
                self.router.set_query_params({ "selected": node_id })

            testgen_component(
                "data_hierarchy",
                props={ "columns": columns_df.to_json(orient="records"), "selected": json.dumps(selected_item) },
                on_change_handlers={ "TreeNodeSelected": on_tree_node_select },
                event_handlers={ "MetadataChanged": on_metadata_changed },
            )


def on_metadata_changed(metadata: dict) -> None:
    schema = st.session_state["dbschema"]
    item_type, item_id = metadata["id"].split("_", 2)

    if item_type == "table":
        update_table = "data_table_chars"
        id_column = "table_id"
    else:
        update_table = "data_column_chars"
        id_column = "column_id"

    attributes = [
        "data_source",
        "source_system",
        "source_process",
        "business_domain",
        "stakeholder_group",
        "transform_level",
        "aggregation_level"
    ]
    cde_value_map = {
        True: "TRUE",
        False: "FALSE",
        None: "NULL",
    }
    set_attributes = [ f"{key} = NULLIF('{metadata.get(key) or ''}', '')" for key in attributes ]
    set_attributes.append(f"critical_data_element = {cde_value_map[metadata.get('critical_data_element')]}")

    sql = f"""
        UPDATE {schema}.{update_table}
        SET {', '.join(set_attributes)}
        WHERE {id_column} = '{item_id}';
        """
    db.execute_sql(sql)
    get_selected_item.clear()
    st.rerun()


def render_empty_state(project_code: str) -> bool:
    project_summary_df = project_queries.get_summary_by_code(project_code)
    if project_summary_df["profiling_runs_ct"]: # Without profiling, we don't have any table and column information in db 
        return False

    label="Your project is empty"
    testgen.whitespace(5)
    if not project_summary_df["connections_ct"]:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.Connection,
            action_label="Go to Connections",
            link_href="connections",
        )
    else:
        testgen.empty_state(
            label=label,
            icon=PAGE_ICON,
            message=testgen.EmptyStateMessage.Profiling if project_summary_df["table_groups_ct"] else testgen.EmptyStateMessage.TableGroup,
            action_label="Go to Table Groups",
            link_href="connections:table-groups",
            link_params={ "connection_id": str(project_summary_df["default_connection_id"]) }
        )
    return True


@st.cache_data(show_spinner=False)
def get_table_group_options(project_code):
    schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(schema, project_code)


@st.cache_data(show_spinner="Loading data ...")
def get_table_group_columns(table_group_id: str) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    sql = f"""
    SELECT CONCAT('column_', column_chars.column_id) AS column_id,
        CONCAT('table_', table_chars.table_id) AS table_id,
        column_chars.column_name,
        table_chars.table_name,
        column_chars.general_type,
        column_chars.drop_date AS column_drop_date,
        table_chars.drop_date AS table_drop_date
    FROM {schema}.data_column_chars column_chars
        LEFT JOIN {schema}.data_table_chars table_chars ON (
            column_chars.table_id = table_chars.table_id
        )
    WHERE column_chars.table_groups_id = '{table_group_id}'
    ORDER BY table_name, column_name;
    """
    return db.retrieve_data(sql)


@st.cache_data(show_spinner="Loading data ...")
def get_selected_item(selected: str, table_group_id: str) -> dict | None:
    if not selected:
        return None
    
    schema = st.session_state["dbschema"]
    item_type, item_id = selected.split("_", 2)

    if item_type not in ["table", "column"] or not is_uuid4(item_id):
        return None

    if item_type == "table":
        sql = f"""
        SELECT table_chars.table_name,
            table_chars.table_groups_id::VARCHAR(50) AS table_group_id,
            -- Characteristics
            functional_table_type,
            record_ct,
            table_chars.column_ct,
            data_point_ct,
            add_date AS add_date,
            drop_date AS drop_date,
            -- Metadata
            critical_data_element,
            data_source,
            source_system,
            source_process,
            business_domain,
            stakeholder_group,
            transform_level,
            aggregation_level,
            -- Latest Profile & Test Runs
            last_complete_profile_run_id::VARCHAR(50) AS latest_profile_id,
            profiling_starttime AS latest_profile_date,
            EXISTS(
                SELECT 1
                FROM {schema}.test_results
                WHERE table_groups_id = '{table_group_id}'
                    AND table_name = table_chars.table_name
            ) AS has_test_runs
        FROM {schema}.data_table_chars table_chars
            LEFT JOIN {schema}.profiling_runs ON (
                table_chars.last_complete_profile_run_id = profiling_runs.id
            )
        WHERE table_id = '{item_id}'
            AND table_chars.table_groups_id = '{table_group_id}';
        """
    else:
        sql = f"""
        SELECT column_chars.column_name,
            column_chars.table_name,
            column_chars.table_groups_id::VARCHAR(50) AS table_group_id,
            -- Characteristics
            column_chars.general_type,
            column_chars.column_type,
            column_chars.functional_data_type,
            datatype_suggestion,
            column_chars.add_date AS add_date,
            column_chars.last_mod_date AS last_mod_date,
            column_chars.drop_date AS drop_date,
            -- Column Metadata
            column_chars.critical_data_element,
            column_chars.data_source,
            column_chars.source_system,
            column_chars.source_process,
            column_chars.business_domain,
            column_chars.stakeholder_group,
            column_chars.transform_level,
            column_chars.aggregation_level,
            -- Table Metadata
            table_chars.critical_data_element AS table_critical_data_element,
            table_chars.data_source AS table_data_source,
            table_chars.source_system AS table_source_system,
            table_chars.source_process AS table_source_process,
            table_chars.business_domain AS table_business_domain,
            table_chars.stakeholder_group AS table_stakeholder_group,
            table_chars.transform_level AS table_transform_level,
            table_chars.aggregation_level AS table_aggregation_level,
            -- Latest Profile & Test Runs
            column_chars.last_complete_profile_run_id::VARCHAR(50) AS latest_profile_id,
            run_date AS latest_profile_date,
            EXISTS(
                SELECT 1
                FROM {schema}.test_results
                WHERE table_groups_id = '{table_group_id}'
                    AND table_name = column_chars.table_name
                    AND column_names = column_chars.column_name
            ) AS has_test_runs,
            -- Value Counts
            profile_results.record_ct,
            value_ct,
            distinct_value_ct,
            null_value_ct,
            zero_value_ct,
            -- Alpha
            zero_length_ct,
            filled_value_ct,
            includes_digit_ct,
            numeric_ct,
            date_ct,
            quoted_value_ct,
            lead_space_ct,
            embedded_space_ct,
            avg_embedded_spaces,
            min_length,
            max_length,
            avg_length,
            min_text,
            max_text,
            distinct_std_value_ct,
            distinct_pattern_ct,
            std_pattern_match,
            top_freq_values,
            top_patterns,
            -- Numeric
            min_value,
            min_value_over_0,
            max_value,
            avg_value,
            stdev_value,
            percentile_25,
            percentile_50,
            percentile_75,
            -- Date
            min_date,
            max_date,
            before_1yr_date_ct,
            before_5yr_date_ct,
            before_20yr_date_ct,
            within_1yr_date_ct,
            within_1mo_date_ct,
            future_date_ct,
            -- Boolean
            boolean_true_ct
        FROM {schema}.data_column_chars column_chars
            LEFT JOIN {schema}.data_table_chars table_chars ON (
                column_chars.table_id = table_chars.table_id
            )
            LEFT JOIN {schema}.profile_results ON (
                column_chars.last_complete_profile_run_id = profile_results.profile_run_id
                AND column_chars.column_name = profile_results.column_name
            )
        WHERE column_id = '{item_id}'
            AND column_chars.table_groups_id = '{table_group_id}';
        """

    item_df = db.retrieve_data(sql)
    if not item_df.empty:
        # to_json converts datetimes, NaN, etc, to JSON-safe values (Note: to_dict does not)
        item = json.loads(item_df.to_json(orient="records"))[0]
        item["id"] = selected
        item["type"] = item_type
        item["latest_anomalies"] = get_profile_anomalies(item["latest_profile_id"], item["table_name"], item.get("column_name"))
        item["latest_test_issues"] = get_latest_test_issues(item["table_group_id"], item["table_name"], item.get("column_name"))
        return item


@st.cache_data(show_spinner=False)
def get_profile_anomalies(profile_run_id: str, table_name: str, column_name: str | None = None) -> dict | None:
    schema = st.session_state["dbschema"]

    column_condition = ""
    if column_name:
        column_condition = f"AND column_name = '{column_name}'"
    
    sql = f"""
    WITH pii_results AS (
        SELECT id,
            CASE
                WHEN detail LIKE 'Risk: HIGH%%' THEN 'High'
                WHEN detail LIKE 'Risk: MODERATE%%' THEN 'Moderate'
                ELSE null
            END AS pii_risk
        FROM {schema}.profile_anomaly_results
    )
    SELECT column_name,
        anomaly_name,
        issue_likelihood,
        detail,
        pii_risk
    FROM {schema}.profile_anomaly_results anomaly_results
        LEFT JOIN {schema}.profile_anomaly_types anomaly_types ON (
            anomaly_types.id = anomaly_results.anomaly_id
        )
        LEFT JOIN pii_results ON (
            anomaly_results.id = pii_results.id
        )
    WHERE profile_run_id = '{profile_run_id}'
        AND table_name = '{table_name}'
        {column_condition}
        AND COALESCE(disposition, 'Confirmed') = 'Confirmed'
    ORDER BY
        CASE issue_likelihood
            WHEN 'Definite' THEN 1
            WHEN 'Likely' THEN 2
            WHEN 'Possible' THEN 3
            ELSE 4
        END,
        CASE pii_risk
            WHEN 'High' THEN 1
            WHEN 'Moderate' THEN 2
            ELSE 3
        END,
        column_name;
    """

    df = db.retrieve_data(sql)
    return json.loads(df.to_json(orient="records"))


@st.cache_data(show_spinner=False)
def get_latest_test_issues(table_group_id: str, table_name: str, column_name: str | None = None) -> dict | None:
    schema = st.session_state["dbschema"]

    column_condition = ""
    if column_name:
        column_condition = f"AND column_names = '{column_name}'"
    
    sql = f"""
    SELECT test_results.id::VARCHAR(50),
        column_names AS column_name,
        test_name_short AS test_name,
        result_status,
        result_message,
        test_suite,
        test_results.test_run_id::VARCHAR(50),
        test_starttime AS test_run_date
    FROM {schema}.test_suites
        LEFT JOIN {schema}.test_runs ON (
            test_suites.last_complete_test_run_id = test_runs.id
        )
        LEFT JOIN {schema}.test_results ON (
            test_runs.id = test_results.test_run_id
        )
        LEFT JOIN {schema}.test_types ON (
            test_results.test_type = test_types.test_type
        )
    WHERE test_suites.table_groups_id = '{table_group_id}'
        AND table_name = '{table_name}'
        {column_condition}
        AND result_status <> 'Passed'
        AND COALESCE(disposition, 'Confirmed') = 'Confirmed'
    ORDER BY
        CASE result_status
            WHEN 'Failed' THEN 1
            WHEN 'Warning' THEN 2
            ELSE 3
        END,
        column_name;
    """

    df = db.retrieve_data(sql)
    return json.loads(df.to_json(orient="records"))
