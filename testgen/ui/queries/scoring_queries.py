from collections import defaultdict
from typing import Literal

import pandas as pd
import streamlit as st

from testgen.common.models import engine
from testgen.common.models.scores import ScoreCard, ScoreCategory, ScoreDefinition, SelectedIssue
from testgen.common import read_template_sql_file
import testgen.ui.services.database_service as db


def get_all_score_cards(
    project_code: str,
    sorted_by: Literal["name", "score"] = "name",
    filter_term: str | None = None
) -> list["ScoreCard"]:
    definitions = ScoreDefinition.all(project_code=project_code, name_filter=filter_term, sorted_by=sorted_by)
    score_cards: list[ScoreCard] = []
    root_keys: list[str] = ["score", "profiling_score", "testing_score", "cde_score"]

    for definition in definitions:
        score_card: ScoreCard = {
            "id": definition.id,
            "project_code": project_code,
            "name": definition.name,
            "categories": [],
            "definition": definition,
        }
        for result in sorted(definition.results, key=lambda r: r.category):
            if result.category in root_keys:
                score_card[result.category] = result.score
                continue
            score_card["categories"].append({"label": result.category, "score": result.score})
        score_cards.append(score_card)
    return score_cards


def get_score_card(definition: ScoreDefinition) -> "ScoreCard":
    overall_score_query_template_file = "get_overall_scores_by_column.sql"
    categories_query_template_file = "get_category_scores_by_column.sql"
    if definition.should_use_dimension_scores():
        overall_score_query_template_file = "get_overall_scores_by_dimension.sql"
        categories_query_template_file = "get_category_scores_by_dimension.sql"

    filters = _get_score_definition_filters(definition)
    overall_scores = db.retrieve_data(read_template_sql_file(
        overall_score_query_template_file,
        sub_directory="score_cards",
    ).replace("{filters}", filters))
    overall_scores = overall_scores.iloc[0].to_dict() if not overall_scores.empty else {}

    categories_scores = []
    if (category := definition.category):
        categories_scores = db.retrieve_data(read_template_sql_file(
            categories_query_template_file,
            sub_directory="score_cards",
        ).replace("{category}", category.value).replace("{filters}", filters))
        categories_scores = [category.to_dict() for _, category in categories_scores.iterrows()]

    return {
        "id": definition.id,
        "project_code": definition.project_code,
        "name": definition.name,
        "score": overall_scores.get("score") if definition.total_score else None,
        "cde_score": overall_scores.get("cde_score") if definition.cde_score else None,
        "profiling_score": overall_scores.get("profiling_score") if definition.total_score else None,
        "testing_score": overall_scores.get("testing_score") if definition.total_score else None,
        "categories": categories_scores,
        "definition": definition,
    }


def get_score_card_breakdown(
    definition: ScoreDefinition,
    score_type: Literal["score", "cde_score"],
    group_by: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
) -> list[dict]:
    query_template_file = "get_score_card_breakdown_by_column.sql"
    if definition.should_use_dimension_scores() or group_by == "dq_dimension":
        query_template_file = "get_score_card_breakdown_by_dimension.sql"

    columns = {
        "column_name": ["table_name", "column_name"],
    }.get(group_by, [group_by])
    filters = _get_score_definition_filters(definition, cde_only=score_type == "cde_score")
    join_condition = " AND ".join([f"test_records.{column} = profiling_records.{column}" for column in columns])
    records_count_filters = _get_score_definition_filters(
        definition,
        cde_only=score_type == "cde_score",
        prefix="profiling_records.",
    )
    non_null_columns = [f"COALESCE(profiling_records.{col}, test_records.{col}) AS {col}" for col in columns]

    query = (
        read_template_sql_file(query_template_file, sub_directory="score_cards")
        .replace("{columns}", ", ".join(columns))
        .replace("{group_by}", group_by)
        .replace("{filters}", filters)
        .replace("{join_condition}", join_condition)
        .replace("{records_count_filters}", records_count_filters)
        .replace("{non_null_columns}", ", ".join(non_null_columns))
    )
    results = pd.read_sql_query(query, engine)

    return [row.to_dict() for _, row in results.iterrows()]


def get_score_card_issues(
    definition: ScoreDefinition,
    score_type: Literal["score", "cde_score"],
    group_by: Literal["column_name", "table_name", "dq_dimension", "semantic_data_type"],
    value: str,
):
    query_template_file = "get_score_card_issues_by_column.sql"
    if definition.should_use_dimension_scores() or group_by == "dq_dimension":
        query_template_file = "get_score_card_issues_by_dimension.sql"

    value_ = value
    filters = _get_score_definition_filters(definition, cde_only=score_type == "cde_score")
    if group_by == "column_name":
        table_name, value_ = value.split(".")
        filters = filters + f" AND table_name = '{table_name}'"

    dq_dimension_filter = ""
    if group_by == "dq_dimension":
        dq_dimension_filter = f" AND dq_dimension = '{value_}'"

    query = (
        read_template_sql_file(query_template_file, sub_directory="score_cards")
        .replace("{filters}", filters)
        .replace("{group_by}", group_by)
        .replace("{value}", value_)
        .replace("{dq_dimension_filter}", dq_dimension_filter)
    )
    results = pd.read_sql_query(query, engine)
    return [row.to_dict() for _, row in results.iterrows()]


def _get_score_definition_filters(
    definition: ScoreDefinition,
    cde_only: bool = False,
    prefix: str | None = None,
) -> str:
    values_by_field = defaultdict(list)
    for filter_ in definition.filters:
        values_by_field[filter_.field].append(f"'{filter_.value}'")
    values_by_field["project_code"].append(f"'{definition.project_code}'")
    if cde_only:
        values_by_field["critical_data_element"].append("true")

    return " AND ".join([
        f"{prefix or ''}{field} = {values[0]}"
        if len(values) == 1 else
        f"{prefix or ''}{field} IN ({', '.join(values)})"
        for field, values in values_by_field.items()
    ])


def get_score_card_issue_reports(selected_issues: list["SelectedIssue"]):
    profile_ids = []
    test_ids = []
    for issue in selected_issues:
        id_list = profile_ids if issue["issue_type"] == "hygiene" else test_ids
        id_list.append(issue["id"])

    schema: str = st.session_state["dbschema"]
    results = []
    if profile_ids:
        profile_query = f"""
        SELECT
            results.id::VARCHAR,
            'hygiene' AS issue_type,
            types.issue_likelihood,
            runs.profiling_starttime,
            types.anomaly_name,
            types.anomaly_description,
            results.detail,
            results.schema_name,
            results.table_name,
            results.column_name,
            results.column_type,
            groups.table_groups_name,
            results.disposition,
            results.profile_run_id::VARCHAR,
            types.suggested_action,
            results.table_groups_id::VARCHAR,
            results.anomaly_id::VARCHAR
        FROM {schema}.profile_anomaly_results results
        INNER JOIN {schema}.profile_anomaly_types types
            ON results.anomaly_id = types.id
        INNER JOIN {schema}.profiling_runs runs
            ON results.profile_run_id = runs.id
        INNER JOIN {schema}.table_groups groups
            ON results.table_groups_id = groups.id
        WHERE results.id IN ({",".join([f"'{issue_id}'" for issue_id in profile_ids])});
        """
        profile_results = db.retrieve_data(profile_query)
        results.extend([row.to_dict() for _, row in profile_results.iterrows()])

    if test_ids:
        test_query = f"""
        SELECT
            results.id::VARCHAR AS test_result_id,
            'test' AS issue_type,
            results.result_status,
            results.test_time,
            types.test_name_short,
            types.test_name_long,
            results.test_description,
            results.result_measure::NUMERIC(16, 5),
            types.measure_uom_description,
            results.threshold_value::NUMERIC(16, 5),
            types.threshold_description,
            results.schema_name,
            results.table_name,
            results.column_names,
            groups.table_groups_name,
            suites.test_suite,
            types.dq_dimension,
            CASE
                WHEN results.result_code <> 1 THEN results.disposition
                ELSE 'Passed'
            END as disposition,
            results.test_run_id::VARCHAR,
            types.usage_notes,
            types.test_type,
            results.auto_gen,
            results.test_suite_id,
            results.test_definition_id::VARCHAR as test_definition_id_runtime,
            results.table_groups_id::VARCHAR,
            types.id::VARCHAR AS test_type_id
        FROM {schema}.test_results results
        INNER JOIN {schema}.test_types types
            ON (results.test_type = types.test_type)
        INNER JOIN {schema}.test_suites suites
            ON (results.test_suite_id = suites.id)
        INNER JOIN {schema}.table_groups groups
            ON (results.table_groups_id = groups.id)
        WHERE results.id IN ({",".join([f"'{issue_id}'" for issue_id in test_ids])});
        """
        test_results = db.retrieve_data(test_query)
        results.extend([row.to_dict() for _, row in test_results.iterrows()])

    return results


def get_score_category_values(project_code: str) -> dict[ScoreCategory, list[str]]:
    values = defaultdict(list)
    categories = [
        "table_groups_name",
        "data_location",
        "data_source",
        "source_system",
        "source_process",
        "business_domain",
        "stakeholder_group",
        "transform_level",
    ]

    quote = lambda v: "'{}'".format(v)
    query = " UNION ".join([
        f"""
        SELECT DISTINCT
            UNNEST(array[{', '.join([quote(c) for c in categories])}]) as category,
            UNNEST(array[{', '.join(categories)}]) AS value
        FROM v_dq_test_scoring_latest_by_column
        WHERE project_code = '{project_code}'
        """,
        f"""
        SELECT DISTINCT
            UNNEST(array[{', '.join([quote(c) for c in categories])}]) as category,
            UNNEST(array[{', '.join(categories)}]) AS value
        FROM v_dq_profile_scoring_latest_by_column
        WHERE project_code = '{project_code}'
        """,
        f"""
        SELECT DISTINCT 
            UNNEST(array['dq_dimension']) as category,
            UNNEST(array[dq_dimension]) AS value
        FROM v_dq_test_scoring_latest_by_dimension
        WHERE project_code = '{project_code}'
        """,
        f"""
        SELECT DISTINCT
            UNNEST(array['dq_dimension']) as category,
            UNNEST(array[dq_dimension]) AS value
        FROM v_dq_profile_scoring_latest_by_dimension
        WHERE project_code = '{project_code}'
        """,
    ])
    results = db.retrieve_data(query)
    for _, row in results.iterrows():
        if row["category"] and row["value"]:
            values[row["category"]].append(row["value"])
    return values
