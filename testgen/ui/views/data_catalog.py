import json
import time
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
from testgen.ui.components.widgets.download_dialog import (
    FILE_DATA_TYPE,
    PROGRESS_UPDATE_TYPE,
    download_dialog,
    get_excel_file_data,
)
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.queries import project_queries
from testgen.ui.queries.profiling_queries import (
    TAG_FIELDS,
    get_column_by_id,
    get_columns_by_id,
    get_hygiene_issues,
    get_table_by_id,
)
from testgen.ui.services import user_session_service
from testgen.ui.session import session, temp_value
from testgen.ui.views.dialogs.column_history_dialog import column_history_dialog
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
                "ExportClicked": lambda columns: download_dialog(
                    dialog_title="Download Excel Report",
                    file_content_func=get_excel_report_data,
                    args=(selected_table_group["table_groups_name"], columns),
                ),
                "RemoveTableClicked": remove_table_dialog,
                "DataPreviewClicked": lambda item: data_preview_dialog(
                    item["table_group_id"],
                    item["schema_name"],
                    item["table_name"],
                    item.get("column_name"),
                ),
                "HistoryClicked": lambda item: column_history_dialog(
                    item["table_group_id"],
                    item["schema_name"],
                    item["table_name"],
                    item["column_name"],
                    item["add_date"],
                ),
            },
            event_handlers={ "TagsChanged": partial(on_tags_changed, spinner_container) },
        )


def on_table_group_selected(table_group_id: str | None) -> None:
    Router().set_query_params({ "table_group_id": table_group_id })


def on_item_selected(item_id: str | None) -> None:
    Router().set_query_params({ "selected": item_id })


def get_excel_report_data(update_progress: PROGRESS_UPDATE_TYPE, table_group: str, columns: list[str]) -> None:
    data = get_columns_by_id(
        [ col.split("_")[1] for col in columns ],
        include_tags=True,
    )
    data = pd.DataFrame(data)

    for key in ["column_type", "datatype_suggestion"]:
        data[key] = data[key].apply(lambda val: val.lower() if not pd.isna(val) else None)

    for key in ["avg_embedded_spaces", "avg_length", "avg_value", "stdev_value"]:
        data[key] = data[key].apply(lambda val: round(val, 2) if not pd.isna(val) else None)

    for key in ["min_date", "max_date", "add_date", "last_mod_date", "drop_date"]:
        data[key] = data[key].apply(
            lambda val: datetime.fromtimestamp(val / 1000).strftime("%b %-d %Y, %-I:%M %p") if not pd.isna(val) else None
        )

    for key in ["data_source", "source_system", "source_process", "business_domain", "stakeholder_group", "transform_level", "aggregation_level", "data_product"]:
        data[key] = data.apply(
            lambda col: col[key] or col[f"table_{key}"] or col.get(f"table_group_{key}"),
            axis=1,
        )

    type_map = {"A": "Alpha", "B": "Boolean", "D": "Datetime", "N": "Numeric"}
    data["general_type"] = data["general_type"].apply(lambda val: type_map.get(val))

    data["critical_data_element"] = data.apply(
        lambda col: "Yes" if col["critical_data_element"] or col["table_critical_data_element"] else None,
        axis=1,
    )
    data["top_freq_values"] = data["top_freq_values"].apply(
        lambda val: "\n".join([ f"{part.split(" | ")[1]} | {part.split(" | ")[0]}" for part in val[2:].split("\n| ") ])
        if val
        else None
    )
    data["top_patterns"] = data["top_patterns"].apply(
        lambda val: "".join([ f"{part}{'\n' if index % 2 else ' | '}" for index, part in enumerate(val.split(" | ")) ])
        if val
        else None
    )

    file_columns = {
        "schema_name": {"header": "Schema"},
        "table_name": {"header": "Table"},
        "column_name": {"header": "Column"},
        "critical_data_element": {},
        "ordinal_position": {"header": "Position"},
        "general_type": {},
        "column_type": {"header": "Data type"},
        "datatype_suggestion": {"header": "Suggested data type"},
        "functional_data_type": {"header": "Semantic data type"},
        "add_date": {"header": "First detected"},
        "last_mod_date": {"header": "Modification detected"},
        "drop_date": {"header": "Drop detected"},
        "record_ct": {"header": "Record count"},
        "value_ct": {"header": "Value count"},
        "distinct_value_ct": {"header": "Distinct values"},
        "null_value_ct": {"header": "Null values"},
        "zero_value_ct": {"header": "Zero values"},
        "zero_length_ct": {"header": "Zero length"},
        "filled_value_ct": {"header": "Dummy values"},
        "mixed_case_ct": {"header": "Mixed case"},
        "lower_case_ct": {"header": "Lower case"},
        "non_alpha_ct": {"header": "Non-alpha"},
        "includes_digit_ct": {"header": "Includes digits"},
        "numeric_ct": {"header": "Numeric values"},
        "date_ct": {"header": "Date values"},
        "quoted_value_ct": {"header": "Quoted values"},
        "lead_space_ct": {"header": "Leading spaces"},
        "embedded_space_ct": {"header": "Embedded spaces"},
        "avg_embedded_spaces": {"header": "Average embedded spaces"},
        "min_length": {"header": "Minimum length"},
        "max_length": {"header": "Maximum length"},
        "avg_length": {"header": "Average length"},
        "min_text": {"header": "Minimum text", "wrap": True},
        "max_text": {"header": "Maximum text", "wrap": True},
        "distinct_std_value_ct": {"header": "Distinct standard values"},
        "distinct_pattern_ct": {"header": "Distinct patterns"},
        "std_pattern_match": {"header": "Standard pattern match"},
        "top_freq_values": {"header": "Frequent values", "wrap": True},
        "top_patterns": {"header": "Frequent patterns", "wrap": True},
        "min_value": {"header": "Minimum value"},
        "min_value_over_0": {"header": "Minimum value > 0"},
        "max_value": {"header": "Maximum value"},
        "avg_value": {"header": "Average value"},
        "stdev_value": {"header": "Standard deviation"},
        "percentile_25": {"header": "25th percentile"},
        "percentile_50": {"header": "Median value"},
        "percentile_75": {"header": "75th percentile"},
        "min_date": {"header": "Minimum date (UTC)"},
        "max_date": {"header": "Maximum date (UTC)"},
        "before_1yr_date_ct": {"header": "Before 1 year"},
        "before_5yr_date_ct": {"header": "Before 5 years"},
        "before_20yr_date_ct": {"header": "Before 20 years"},
        "within_1yr_date_ct": {"header": "Within 1 year"},
        "within_1mo_date_ct": {"header": "Within 1 month"},
        "future_date_ct": {"header": "Future dates"},
        "boolean_true_ct": {"header": "Boolean true values"},
        "description": {"wrap": True},
        "data_source": {},
        "source_system": {},
        "source_process": {},
        "business_domain": {},
        "stakeholder_group": {},
        "transform_level": {},
        "aggregation_level": {},
        "data_product": {},
    }
    return get_excel_file_data(
        data,
        "Data Catalog Columns",
        details={"Table group": table_group},
        columns=file_columns,
        update_progress=update_progress,
    )


@st.dialog(title="Remove Table from Catalog")
def remove_table_dialog(item: dict) -> None:
    remove_clicked, set_remove_clicked = temp_value("data-catalog:confirm-remove-table-val")
    st.html(f"Are you sure you want to remove the table <b>{item['table_name']}</b> from the data catalog?")
    st.warning("This action cannot be undone.")

    _, button_column = st.columns([.85, .15])
    with button_column:
        testgen.button(
            label="Remove",
            type_="flat",
            color="warn",
            key="data-catalog:confirm-remove-table-btn",
            on_click=lambda: set_remove_clicked(True),
        )

    if remove_clicked():
        schema = st.session_state["dbschema"]
        db.execute_sql(f"""
        DELETE FROM {schema}.data_column_chars
        WHERE table_id = '{item["id"]}';
        """)
        db.execute_sql(f"""
        DELETE FROM {schema}.data_table_chars
        WHERE table_id = '{item["id"]}';
        """)

        st.success("Table has been removed.")
        time.sleep(1)
        for func in [ get_table_group_columns, get_tag_values ]:
            func.clear()
        st.session_state["data_catalog:last_saved_timestamp"] = datetime.now().timestamp()
        st.rerun()


def on_tags_changed(spinner_container: DeltaGenerator, payload: dict) -> FILE_DATA_TYPE:
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
                db.execute_sql_raw(f"""
                WITH selected as (
                    SELECT UNNEST(ARRAY [{", ".join([ f"'{item}'" for item in tables ])}]) AS table_id
                )
                UPDATE {schema}.data_table_chars
                SET {', '.join(set_attributes)}
                FROM {schema}.data_table_chars dtc
                    INNER JOIN selected ON (dtc.table_id = selected.table_id::UUID)
                WHERE dtc.table_id = data_table_chars.table_id;
                """)
                

            if columns:
                db.execute_sql_raw(f"""
                WITH selected as (
                    SELECT UNNEST(ARRAY [{", ".join([ f"'{item}'" for item in columns ])}]) AS column_id
                )
                UPDATE {schema}.data_column_chars
                SET {', '.join(set_attributes)}
                FROM {schema}.data_column_chars dcc
                    INNER JOIN selected ON (dcc.column_id = selected.column_id::UUID)
                WHERE dcc.column_id = data_column_chars.column_id;
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
        table_chars.record_ct,
        profile_results.value_ct,
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
        LEFT JOIN {schema}.profile_results ON (
            column_chars.last_complete_profile_run_id = profile_results.profile_run_id
            AND column_chars.table_name = profile_results.table_name
            AND column_chars.column_name = profile_results.column_name
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
        item = get_table_by_id(item_id)
    elif item_type == "column":
        item = get_column_by_id(item_id, include_tags=True, include_has_test_runs=True, include_scores=True)
    else:
        return None

    if item:
        item["dq_score"] = friendly_score(score(item["dq_score_profiling"], item["dq_score_testing"]))
        item["dq_score_profiling"] = friendly_score(item["dq_score_profiling"])
        item["dq_score_testing"] = friendly_score(item["dq_score_testing"])
        item["hygiene_issues"] = get_hygiene_issues(item["profile_run_id"], item["table_name"], item.get("column_name"))
        item["test_issues"] = get_latest_test_issues(item["table_group_id"], item["table_name"], item.get("column_name"))
        item["test_suites"] = get_related_test_suites(item["table_group_id"], item["table_name"], item.get("column_name"))
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
def get_related_test_suites(table_group_id: str, table_name: str, column_name: str | None = None) -> dict | None:
    schema = st.session_state["dbschema"]

    column_condition = ""
    if column_name:
        column_condition = f"AND column_name = '{column_name}'"

    sql = f"""
    SELECT
        test_suites.id::VARCHAR,
        test_suite AS name,
        COUNT(*) AS test_count
    FROM {schema}.test_definitions
        LEFT JOIN {schema}.test_suites ON (
            test_definitions.test_suite_id = test_suites.id
        )
    WHERE test_suites.table_groups_id = '{table_group_id}'
        AND table_name = '{table_name}'
        {column_condition}
    GROUP BY test_suites.id
    ORDER BY test_suite;
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
