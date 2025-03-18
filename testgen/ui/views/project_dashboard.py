import typing

import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import project_queries
from testgen.ui.services import test_suite_service, user_session_service
from testgen.ui.session import session
from testgen.utils import format_field, friendly_score, score

STALE_PROFILE_DAYS = 30
PAGE_TITLE = "Project Dashboard"
PAGE_ICON = "home"


class ProjectDashboardPage(Page):
    path = "project-dashboard"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        order=0,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
    )

    def render(self, project_code: str | None = None, **_kwargs):
        testgen.page_header(
            PAGE_TITLE,
            "introduction-to-dataops-testgen",
        )

        project_code = project_code or session.project
        table_groups = get_table_groups_summary(project_code)
        project_summary_df = project_queries.get_summary_by_code(project_code)

        table_groups_fields: list[str] = [
            "id",
            "table_groups_name",
            "latest_profile_id",
            "latest_profile_start",
            "latest_profile_table_ct",
            "latest_profile_column_ct",
            "latest_anomalies_ct",
            "latest_anomalies_definite_ct",
            "latest_anomalies_likely_ct",
            "latest_anomalies_possible_ct",
            "latest_anomalies_dismissed_ct",
            "latest_tests_start",
            "latest_tests_suite_ct",
            "latest_tests_ct",
            "latest_tests_passed_ct",
            "latest_tests_warning_ct",
            "latest_tests_failed_ct",
            "latest_tests_error_ct",
            "latest_tests_dismissed_ct",
        ]
        test_suite_fields: list[str] = [
            "id",
            "test_suite",
            "test_ct",
            "latest_auto_gen_date",
            "latest_run_start",
            "latest_run_id",
            "last_run_test_ct",
            "last_run_passed_ct",
            "last_run_warning_ct",
            "last_run_failed_ct",
            "last_run_error_ct",
            "last_run_dismissed_ct",
        ]

        table_groups_sort = st.session_state.get("overview_table_groups_sort") or "latest_activity_date"
        expanded_table_groups = st.session_state.get("overview_table_groups_expanded", [])

        testgen.testgen_component(
            "project_dashboard",
            props={
                "project": {
                    "table_groups_count": len(table_groups.index),
                    "test_suites_count": int(table_groups["latest_tests_suite_ct"].sum()),
                    "test_definitions_count": int(table_groups["latest_tests_ct"].sum()),
                    "test_runs_count": int(project_summary_df["test_runs_ct"]),
                    "profiling_runs_count": int(project_summary_df["profiling_runs_ct"]),
                    "connections_count": int(project_summary_df["connections_ct"]),
                    "default_connection_id": str(project_summary_df["default_connection_id"]),
                },
                "table_groups": [
                    {
                        **{field: format_field(table_group[field]) for field in table_groups_fields},
                        "test_suites": [
                            { field: format_field(test_suite[field]) for field in test_suite_fields}
                            for _, test_suite in test_suite_service.get_by_project(project_code, table_group_id).iterrows()
                        ] if table_group_id in expanded_table_groups else None,
                        "expanded": table_group_id in expanded_table_groups,
                        "dq_score": friendly_score(score(table_group["dq_score_profiling"], table_group["dq_score_testing"])),
                        "dq_score_profiling": friendly_score(table_group["dq_score_profiling"]),
                        "dq_score_testing": friendly_score(table_group["dq_score_testing"]),
                    }
                    for _, table_group in table_groups.iterrows()
                    if (table_group_id := str(table_group["id"]))
                ],
                "table_groups_sort_options": [
                    {
                        "label": "Table group name",
                        "value": "table_groups_name",
                        "selected": table_groups_sort == "table_groups_name",
                    },
                    {
                        "label": "Latest activity",
                        "value": "latest_activity_date",
                        "selected": table_groups_sort == "latest_activity_date",
                    },
                    {
                        "label": "Lowest score",
                        "value": "lowest_score",
                        "selected": table_groups_sort == "lowest_score",
                    },
                ],
            },
            on_change_handlers={
                "TableGroupExpanded": on_table_group_expanded,
                "TableGroupCollapsed": on_table_group_collapsed,
            },
            event_handlers={},
        )


def on_table_group_expanded(table_group_id: str) -> None:
    expanded_table_groups = st.session_state.get("overview_table_groups_expanded", [])
    expanded_table_groups.append(table_group_id)
    st.session_state["overview_table_groups_expanded"] = expanded_table_groups


def on_table_group_collapsed(table_group_id: str) -> None:
    expanded_table_groups = st.session_state.get("overview_table_groups_expanded", [])
    try:
        expanded_table_groups.remove(table_group_id)
    except ValueError: ...
    st.session_state["overview_table_groups_expanded"] = expanded_table_groups


def get_table_groups_summary(project_code: str) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    sql = f"""
    WITH latest_profile AS (
        SELECT latest_run.table_groups_id,
            latest_run.id,
            latest_run.profiling_starttime,
            latest_run.table_ct,
            latest_run.column_ct,
            latest_run.anomaly_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                    AND anomaly_types.issue_likelihood = 'Definite' THEN 1
                    ELSE 0
                END
            ) as definite_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                    AND anomaly_types.issue_likelihood = 'Likely' THEN 1
                    ELSE 0
                END
            ) as likely_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                    AND anomaly_types.issue_likelihood = 'Possible' THEN 1
                    ELSE 0
                END
            ) as possible_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') IN ('Dismissed', 'Inactive')
                    AND anomaly_types.issue_likelihood <> 'Potential PII' THEN 1
                    ELSE 0
                END
            ) as dismissed_ct
        FROM {schema}.table_groups groups
            LEFT JOIN {schema}.profiling_runs latest_run ON (
                groups.last_complete_profile_run_id = latest_run.id
            )
            LEFT JOIN {schema}.profile_anomaly_results latest_anomalies ON (
                latest_run.id = latest_anomalies.profile_run_id
            )
            LEFT JOIN {schema}.profile_anomaly_types anomaly_types ON (
                anomaly_types.id = latest_anomalies.anomaly_id
            )
        GROUP BY latest_run.id
    ),
    latest_tests AS (
        SELECT suites.table_groups_id,
            MAX(latest_run.test_starttime) AS test_starttime,
            COUNT(DISTINCT latest_run.test_suite_id) as test_suite_ct,
            COUNT(latest_results.id) as test_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_results.disposition, 'Confirmed') = 'Confirmed'
                    AND latest_results.result_status = 'Passed' THEN 1
                    ELSE 0
                END
            ) as passed_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_results.disposition, 'Confirmed') = 'Confirmed'
                    AND latest_results.result_status = 'Warning' THEN 1
                    ELSE 0
                END
            ) as warning_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_results.disposition, 'Confirmed') = 'Confirmed'
                    AND latest_results.result_status = 'Failed' THEN 1
                    ELSE 0
                END
            ) as failed_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_results.disposition, 'Confirmed') = 'Confirmed'
                    AND latest_results.result_status = 'Error' THEN 1
                    ELSE 0
                END
            ) as error_ct,
            SUM(
                CASE
                    WHEN COALESCE(latest_results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                    ELSE 0
                END
            ) as dismissed_ct
        FROM {schema}.test_suites suites
            LEFT JOIN {schema}.test_runs latest_run ON (
                suites.last_complete_test_run_id = latest_run.id
            )
            LEFT JOIN {schema}.test_results latest_results ON (
                latest_run.id = latest_results.test_run_id
            )
        GROUP BY suites.table_groups_id
    )
    SELECT groups.id::VARCHAR(50),
        groups.table_groups_name,
        groups.dq_score_profiling,
        groups.dq_score_testing,
        latest_profile.id as latest_profile_id,
        latest_profile.profiling_starttime as latest_profile_start,
        latest_profile.table_ct as latest_profile_table_ct,
        latest_profile.column_ct as latest_profile_column_ct,
        latest_profile.anomaly_ct as latest_anomalies_ct,
        latest_profile.definite_ct as latest_anomalies_definite_ct,
        latest_profile.likely_ct as latest_anomalies_likely_ct,
        latest_profile.possible_ct as latest_anomalies_possible_ct,
        latest_profile.dismissed_ct as latest_anomalies_dismissed_ct,
        latest_tests.test_starttime as latest_tests_start,
        latest_tests.test_suite_ct as latest_tests_suite_ct,
        latest_tests.test_ct as latest_tests_ct,
        latest_tests.passed_ct as latest_tests_passed_ct,
        latest_tests.warning_ct as latest_tests_warning_ct,
        latest_tests.failed_ct as latest_tests_failed_ct,
        latest_tests.error_ct as latest_tests_error_ct,
        latest_tests.dismissed_ct as latest_tests_dismissed_ct
    FROM {schema}.table_groups as groups
        LEFT JOIN latest_profile ON (groups.id = latest_profile.table_groups_id)
        LEFT JOIN latest_tests ON (groups.id = latest_tests.table_groups_id)
    WHERE groups.project_code = '{project_code}';
    """

    return db.retrieve_data(sql)
