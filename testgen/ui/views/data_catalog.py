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
from testgen.ui.queries.profiling_queries import get_column_by_id, get_hygiene_issues, get_table_by_id
from testgen.ui.session import session
from testgen.ui.views.dialogs.run_profiling_dialog import run_profiling_dialog
from testgen.utils import friendly_score, score

PAGE_ICON = "dataset"
PAGE_TITLE = "Data Catalog"


class DataCatalogPage(Page):
    path = "data-catalog"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon=PAGE_ICON, label=PAGE_TITLE, section="Data Profiling", order=0)

    def render(self, project_code: str | None = None, table_group_id: str | None = None, selected: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
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
            if selected_item:
                selected_item["connection_id"] = str(
                    table_groups_df.loc[table_groups_df["id"] == table_group_id].iloc[0]["connection_id"])
            else:
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
                "data_catalog",
                props={ "columns": columns_df.to_json(orient="records"), "selected": json.dumps(selected_item) },
                on_change_handlers={ "TreeNodeSelected": on_tree_node_select },
                event_handlers={ "TagsChanged": on_tags_changed },
            )


def on_tags_changed(tags: dict) -> None:
    schema = st.session_state["dbschema"]

    if tags["type"] == "table":
        update_table = "data_table_chars"
        id_column = "table_id"
        cached_function = get_table_by_id
    else:
        update_table = "data_column_chars"
        id_column = "column_id"
        cached_function = get_column_by_id

    attributes = [
        "description",
        "data_source",
        "source_system",
        "source_process",
        "business_domain",
        "stakeholder_group",
        "transform_level",
        "aggregation_level",
        "data_product"
    ]
    cde_value_map = {
        True: "TRUE",
        False: "FALSE",
        None: "NULL",
    }
    set_attributes = [ f"{key} = NULLIF('{tags.get(key) or ''}', '')" for key in attributes ]
    set_attributes.append(f"critical_data_element = {cde_value_map[tags.get('critical_data_element')]}")

    sql = f"""
        UPDATE {schema}.{update_table}
        SET {', '.join(set_attributes)}
        WHERE {id_column} = '{tags["id"]}';
        """
    db.execute_sql(sql)
    cached_function.clear()
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
        column_chars.functional_data_type,
        column_chars.drop_date AS column_drop_date,
        table_chars.drop_date AS table_drop_date
    FROM {schema}.data_column_chars column_chars
        LEFT JOIN {schema}.data_table_chars table_chars ON (
            column_chars.table_id = table_chars.table_id
        )
    WHERE column_chars.table_groups_id = '{table_group_id}'
    ORDER BY table_name, ordinal_position;
    """
    return db.retrieve_data(sql)


def get_selected_item(selected: str, table_group_id: str) -> dict | None:
    if not selected:
        return None

    item_type, item_id = selected.split("_", 2)

    if item_type == "table":
        item = get_table_by_id(item_id, table_group_id)
    elif item_type == "column":
        item = get_column_by_id(item_id, table_group_id, include_tags=True, include_has_test_runs=True, include_scores=True)
    else:
        return None

    if item:
        item["dq_score"] = friendly_score(score(item["dq_score_profiling"], item["dq_score_testing"]))
        item["dq_score_profiling"] = friendly_score(item["dq_score_profiling"])
        item["dq_score_testing"] = friendly_score(item["dq_score_testing"])
        item["hygiene_issues"] = get_hygiene_issues(item["profile_run_id"], item["table_name"], item.get("column_name"))
        item["test_issues"] = get_latest_test_issues(item["table_group_id"], item["table_name"], item.get("column_name"))
        return item


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
        EXTRACT(EPOCH FROM test_starttime) * 1000 AS test_run_date
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
    return [row.to_dict() for _, row in df.iterrows()]
