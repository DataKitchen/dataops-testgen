import json
import typing
from collections import defaultdict
from datetime import datetime
from functools import partial

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

import testgen.ui.services.database_service as db
import testgen.ui.services.query_service as dq
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import testgen_component
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.queries import project_queries
from testgen.ui.queries.profiling_queries import TAG_FIELDS, get_column_by_id, get_hygiene_issues, get_table_by_id
from testgen.ui.services import user_session_service
from testgen.ui.session import session
from testgen.ui.views.dialogs.data_preview_dialog import data_preview_dialog
from testgen.ui.views.dialogs.run_profiling_dialog import run_profiling_dialog
from testgen.utils import format_field, friendly_score, is_uuid4, score

PAGE_ICON = "dataset"
PAGE_TITLE = "Data Catalog"


class DataCatalogPage(Page):
    path = "data-catalog"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(icon=PAGE_ICON, label=PAGE_TITLE, section="Data Profiling", order=0)

    def render(self, project_code: str, table_group_id: str | None = None, selected: str | None = None, **_kwargs) -> None:
        testgen.page_header(
            PAGE_TITLE,
        )

        _, loading_column = st.columns([.4, .6])
        spinner_container = loading_column.container(key="data_catalog:spinner")

        with spinner_container:
            with st.spinner(text="Loading data ..."):
                # Make sure none of the loading logic use @st.cache_data(show_spinner=True)
                # Otherwise, the testgen_component randomly remounts for no reason when selecting items
                # (something to do with displaying the extra cache spinner next to the custom component)
                # Enclosing the loading logic in a Streamlit container also fixes it

                project_summary = project_queries.get_summary_by_code(project_code)
                user_can_navigate = not user_session_service.user_has_catalog_role()
                table_groups = get_table_group_options(project_code)

                if not table_group_id or table_group_id not in table_groups["id"].values:
                    table_group_id = table_groups.iloc[0]["id"] if not table_groups.empty else None
                    on_table_group_selected(table_group_id)

                columns, selected_item, selected_table_group = pd.DataFrame(), None, None
                if table_group_id:
                    selected_table_group = table_groups.loc[table_groups["id"] == table_group_id].iloc[0]
                    columns = get_table_group_columns(table_group_id)
                    selected_item = get_selected_item(selected, table_group_id)

        if selected_item:
            selected_item["project_code"] = project_code
            selected_item["connection_id"] = format_field(selected_table_group["connection_id"])
        else:
            on_item_selected(None)
        
        testgen_component(
            "data_catalog",
            props={
                "project_summary": {
                    "project_code": project_code,
                    "connections_ct": format_field(project_summary["connections_ct"]),
                    "table_groups_ct": format_field(project_summary["table_groups_ct"]),
                    "default_connection_id": format_field(project_summary["default_connection_id"]),
                },
                "table_group_filter_options": [
                    {
                        "value": format_field(table_group["id"]),
                        "label": format_field(table_group["table_groups_name"]),
                        "selected": str(table_group_id) == str(table_group["id"]),
                    } for _, table_group in table_groups.iterrows()
                ],
                "columns": columns.to_json(orient="records") if not columns.empty else None,
                "selected_item": json.dumps(selected_item),
                "tag_values": get_tag_values(),
                "last_saved_timestamp": st.session_state.get("data_catalog:last_saved_timestamp"),
                "permissions": {
                    "can_edit": user_session_service.user_can_disposition(),
                    "can_navigate": user_can_navigate,
                },
            },
            on_change_handlers={
                "RunProfilingClicked": partial(
                    run_profiling_dialog,
                    project_code,
                    selected_table_group,
                ),
                "TableGroupSelected": on_table_group_selected,
                "ItemSelected": on_item_selected,
                "DataPreviewClicked": lambda item: data_preview_dialog(
                    item["table_group_id"],
                    item["schema_name"],
                    item["table_name"],
                    item.get("column_name"),
                ),
            },
            event_handlers={ "TagsChanged": partial(on_tags_changed, spinner_container) },
        )


def on_table_group_selected(table_group_id: str | None) -> None:
    Router().set_query_params({ "table_group_id": table_group_id })


def on_item_selected(item_id: str | None) -> None:
    Router().set_query_params({ "selected": item_id })

    
def on_tags_changed(spinner_container: DeltaGenerator, payload: dict) -> None:
    attributes = ["description"]
    attributes.extend(TAG_FIELDS)
    cde_value_map = {
        True: "TRUE",
        False: "FALSE",
        None: "NULL",
    }

    tags = payload["tags"]
    set_attributes = [ f"{key} = NULLIF('{tags.get(key) or ''}', '')" for key in attributes if key in tags ]
    if "critical_data_element" in tags:
        set_attributes.append(f"critical_data_element = {cde_value_map[tags.get('critical_data_element')]}")

    tables = []
    columns = []
    for item in payload["items"]:
        id_list = tables if item["type"] == "table" else columns
        id_list.append(item["id"])

    schema = st.session_state["dbschema"]

    with spinner_container:
        with st.spinner("Saving tags"):
            if tables:
                db.execute_sql(f"""
                UPDATE {schema}.data_table_chars
                SET {', '.join(set_attributes)}
                WHERE table_id IN ({", ".join([ f"'{item}'" for item in tables ])});
                """)

            if columns:
                db.execute_sql(f"""
                UPDATE {schema}.data_column_chars
                SET {', '.join(set_attributes)}
                WHERE column_id IN ({", ".join([ f"'{item}'" for item in columns ])});
                """)

    for func in [ get_table_group_columns, get_table_by_id, get_column_by_id, get_tag_values ]:
        func.clear()
    st.session_state["data_catalog:last_saved_timestamp"] = datetime.now().timestamp()
    st.rerun()


@st.cache_data(show_spinner=False)
def get_table_group_options(project_code):
    schema = st.session_state["dbschema"]
    return dq.run_table_groups_lookup_query(schema, project_code)


@st.cache_data(show_spinner=False)
def get_table_group_columns(table_group_id: str) -> pd.DataFrame:
    if not is_uuid4(table_group_id):
        return pd.DataFrame()
    
    schema = st.session_state["dbschema"]
    sql = f"""
    SELECT CONCAT('column_', column_chars.column_id) AS column_id,
        CONCAT('table_', table_chars.table_id) AS table_id,
        column_chars.column_name,
        table_chars.table_name,
        column_chars.general_type,
        column_chars.functional_data_type,
        column_chars.drop_date,
        table_chars.drop_date AS table_drop_date,
        column_chars.critical_data_element,
        table_chars.critical_data_element AS table_critical_data_element,
        {", ".join([ f"column_chars.{tag}" for tag in TAG_FIELDS ])},
        {", ".join([ f"table_chars.{tag} AS table_{tag}" for tag in TAG_FIELDS ])}
    FROM {schema}.data_column_chars column_chars
        LEFT JOIN {schema}.data_table_chars table_chars ON (
            column_chars.table_id = table_chars.table_id
        )
    WHERE column_chars.table_groups_id = '{table_group_id}'
    ORDER BY table_name, ordinal_position;
    """
    return db.retrieve_data(sql)


def get_selected_item(selected: str, table_group_id: str) -> dict | None:
    if not selected or not is_uuid4(table_group_id):
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


@st.cache_data(show_spinner=False)
def get_tag_values() -> dict[str, list[str]]:
    schema = st.session_state["dbschema"]

    quote = lambda v: f"'{v}'"
    sql = f"""
    SELECT DISTINCT
        UNNEST(array[{', '.join([quote(t) for t in TAG_FIELDS])}]) as tag,
        UNNEST(array[{', '.join(TAG_FIELDS)}]) AS value
    FROM {schema}.data_column_chars
    UNION
    SELECT DISTINCT
        UNNEST(array[{', '.join([quote(t) for t in TAG_FIELDS])}]) as tag,
        UNNEST(array[{', '.join(TAG_FIELDS)}]) AS value
    FROM {schema}.data_table_chars
    UNION
    SELECT DISTINCT
        UNNEST(array[{', '.join([quote(t) for t in TAG_FIELDS if t != 'aggregation_level'])}]) as tag,
        UNNEST(array[{', '.join([ t for t in TAG_FIELDS if t != 'aggregation_level'])}]) AS value
    FROM {schema}.table_groups
    ORDER BY value
    """
    df = db.retrieve_data(sql)

    values = defaultdict(list)
    for _, row in df.iterrows():
        if row["tag"] and row["value"]:
            values[row["tag"]].append(row["value"])
    return values
