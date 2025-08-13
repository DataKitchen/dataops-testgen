import logging
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import streamlit as st

from testgen.common.clean_sql import ConcatColumnList
from testgen.common.database.database_service import replace_params
from testgen.common.models.connection import Connection, SQLFlavor
from testgen.common.models.test_definition import TestDefinition
from testgen.common.read_file import replace_templated_functions
from testgen.ui.services.database_service import fetch_from_target_db, fetch_one_from_db
from testgen.utils import to_dataframe

LOG = logging.getLogger("testgen")


@st.cache_data(show_spinner=False)
def get_hygiene_issue_source_data(
    issue_data: dict,
    limit: int | None = None,
) -> tuple[Literal["OK"], None, str, pd.DataFrame] | tuple[Literal["NA", "ND", "ERR"], str, str | None, None]:
    def generate_lookup_query(test_id: str, detail_exp: str, column_names: list[str], sql_flavor: SQLFlavor) -> str:
        if test_id in {"1019", "1020"}:
            start_index = detail_exp.find("Columns: ")
            if start_index == -1:
                columns = [col.strip() for col in column_names.split(",")]
            else:
                start_index += len("Columns: ")
                column_names_str = detail_exp[start_index:]
                columns = [col.strip() for col in column_names_str.split(",")]
            quote = "`" if sql_flavor == "databricks" else '"'
            queries = [
                f"SELECT '{column}' AS column_name, MAX({quote}{column}{quote}) AS max_date_available FROM {{TARGET_SCHEMA}}.{{TABLE_NAME}}"
                for column in columns
            ]
            sql_query = " UNION ALL ".join(queries) + " ORDER BY max_date_available DESC;"
        else:
            sql_query = ""
        return sql_query

    lookup_query = None
    try:
        lookup_data = _get_lookup_data(issue_data["table_groups_id"], issue_data["anomaly_id"], "Profile Anomaly")
        if not lookup_data:
            return "NA", "Source data lookup is not available for this hygiene issue.", None, None

        lookup_query = (
            generate_lookup_query(
                issue_data["anomaly_id"], issue_data["detail"], issue_data["column_name"], lookup_data.sql_flavor
            )
            if lookup_data.lookup_query == "created_in_ui"
            else lookup_data.lookup_query
        )

        if not lookup_query:
            return "NA", "Source data lookup is not available for this hygiene issue.", None, None

        params = {
            "TARGET_SCHEMA": issue_data["schema_name"],
            "TABLE_NAME": issue_data["table_name"],
            "COLUMN_NAME": issue_data["column_name"],
            "DETAIL_EXPRESSION": issue_data["detail"],
            "PROFILE_RUN_DATE": issue_data["profiling_starttime"],
        }
        lookup_query = replace_params(lookup_query, params)
        lookup_query = replace_templated_functions(lookup_query, lookup_data.sql_flavor)

        connection = Connection.get_by_table_group(issue_data["table_groups_id"])
        results = fetch_from_target_db(connection, lookup_query)

        if results:
            df = to_dataframe(results)
            if limit:
                df = df.sample(n=min(len(df), limit)).sort_index()
            return "OK", None, lookup_query, df
        else:
            return (
                "ND",
                "Data that violates hygiene issue criteria is not present in the current dataset.",
                lookup_query,
                None,
            )
    except Exception as e:
        LOG.exception("Source data lookup for hygiene issue encountered an error.")
        return "ERR", f"Source data lookup encountered an error:\n\n{e.args[0]}", lookup_query, None


@st.cache_data(show_spinner=False)
def get_test_issue_source_data(
    issue_data: dict,
    limit: int | None = None,
) -> tuple[Literal["OK"], None, str, pd.DataFrame] | tuple[Literal["NA", "ND", "ERR"], str, str | None, None]:
    lookup_query = None
    try:
        lookup_data = _get_lookup_data(issue_data["table_groups_id"], issue_data["test_type_id"], "Test Results")

        if not lookup_data or not lookup_data.lookup_query:
            return "NA", "Source data lookup is not available for this test.", None, None

        test_definition = TestDefinition.get(issue_data["test_definition_id_current"])
        if not test_definition:
            return "NA", "Test definition no longer exists.", None, None

        params = {
            "TARGET_SCHEMA": issue_data["schema_name"],
            "TABLE_NAME": issue_data["table_name"],
            "COLUMN_NAME": issue_data["column_names"],
            "TEST_DATE": str(issue_data["test_date"]),
            "CUSTOM_QUERY": test_definition.custom_query,
            "BASELINE_VALUE": test_definition.baseline_value,
            "BASELINE_CT": test_definition.baseline_ct,
            "BASELINE_AVG": test_definition.baseline_avg,
            "BASELINE_SD": test_definition.baseline_sd,
            "LOWER_TOLERANCE": test_definition.lower_tolerance,
            "UPPER_TOLERANCE": test_definition.upper_tolerance,
            "THRESHOLD_VALUE": test_definition.threshold_value,
            "SUBSET_CONDITION": test_definition.subset_condition or "1=1",
            "GROUPBY_NAMES": test_definition.groupby_names,
            "HAVING_CONDITION": test_definition.having_condition,
            "MATCH_SCHEMA_NAME": test_definition.match_schema_name,
            "MATCH_TABLE_NAME": test_definition.match_table_name,
            "MATCH_COLUMN_NAMES": test_definition.match_column_names,
            "MATCH_SUBSET_CONDITION": test_definition.match_subset_condition or "1=1",
            "MATCH_GROUPBY_NAMES": test_definition.match_groupby_names,
            "MATCH_HAVING_CONDITION": test_definition.match_having_condition,
            "COLUMN_NAME_NO_QUOTES": issue_data["column_names"],
            "WINDOW_DATE_COLUMN": test_definition.window_date_column,
            "WINDOW_DAYS": test_definition.window_days,
            "CONCAT_COLUMNS": ConcatColumnList(issue_data["column_names"], "<NULL>"),
            "CONCAT_MATCH_GROUPBY": ConcatColumnList(test_definition.match_groupby_names, "<NULL>"),
        }

        lookup_query = replace_params(lookup_data.lookup_query, params)
        lookup_query = replace_templated_functions(lookup_query, lookup_data.sql_flavor)

        connection = Connection.get_by_table_group(issue_data["table_groups_id"])
        results = fetch_from_target_db(connection, lookup_query)

        if results:
            df = to_dataframe(results)
            if limit:
                df = df.sample(n=min(len(df), limit)).sort_index()
            return "OK", None, lookup_query, df
        else:
            return "ND", "Data that violates test criteria is not present in the current dataset.", lookup_query, None
    except Exception as e:
        LOG.exception("Source data lookup for test encountered an error.")
        return "ERR", f"Source data lookup encountered an error:\n\n{e.args[0]}", lookup_query, None


@st.cache_data(show_spinner=False)
def get_test_issue_source_data_custom(
    issue_data: dict,
    limit: int | None = None,
) -> tuple[Literal["OK"], None, str, pd.DataFrame] | tuple[Literal["NA", "ND", "ERR"], str, str | None, None]:
    lookup_query = None
    try:
        lookup_data = _get_lookup_data_custom(issue_data["test_definition_id_current"])

        if not lookup_data or not lookup_data.lookup_query:
            return "NA", "Source data lookup is not available for this test.", None, None

        params = {
            "DATA_SCHEMA": issue_data["schema_name"],
        }
        lookup_query = replace_params(lookup_data.lookup_query, params)

        connection = Connection.get_by_table_group(issue_data["table_groups_id"])
        results = fetch_from_target_db(connection, lookup_query)

        if results:
            df = to_dataframe(results)
            if limit:
                df = df.sample(n=min(len(df), limit)).sort_index()
            return "OK", None, lookup_query, df
        else:
            return "ND", "Data that violates test criteria is not present in the current dataset.", lookup_query, None
    except Exception as e:
        LOG.exception("Source data lookup for custom test encountered an error.")
        return "ERR", f"Source data lookup encountered an error:\n\n{e.args[0]}", lookup_query, None


@dataclass
class LookupData:
    lookup_query: str
    sql_flavor: SQLFlavor | None


def _get_lookup_data(
    table_group_id: str,
    anomaly_id: str,
    error_type: Literal["Profile Anomaly", "Test Results"],
) -> LookupData | None:
    result = fetch_one_from_db(
        """
        SELECT
            t.lookup_query,
            c.sql_flavor
        FROM target_data_lookups t
        INNER JOIN table_groups tg
            ON (:table_group_id = tg.id)
        INNER JOIN connections c
            ON (tg.connection_id = c.connection_id)
            AND (t.sql_flavor = c.sql_flavor)
        WHERE t.error_type = :error_type
            AND t.test_id = :anomaly_id
            AND t.lookup_query > '';
        """,
        {
            "table_group_id": table_group_id,
            "error_type": error_type,
            "anomaly_id": anomaly_id,
        },
    )
    return LookupData(**result) if result else None


def _get_lookup_data_custom(
    test_definition_id: str,
) -> LookupData | None:
    result = fetch_one_from_db(
        """
        SELECT 
            d.custom_query as lookup_query
        FROM test_definitions d
        WHERE d.id = :test_definition_id;
        """,
        {"test_definition_id": test_definition_id},
    )
    return LookupData(**result) if result else None
