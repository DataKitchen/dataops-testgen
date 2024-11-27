import typing
from datetime import datetime

import pandas as pd
import streamlit as st
from pandas.api.types import is_string_dtype

import testgen.ui.services.database_service as db
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.queries import project_queries
from testgen.ui.services import test_suite_service
from testgen.ui.session import session
from testgen.utils import to_int, truncate

STALE_PROFILE_DAYS = 30
PAGE_ICON = "home"


class OverviewPage(Page):
    path = "overview"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon=PAGE_ICON, label="Overview", order=0)

    def render(self, project_code: str | None = None, **_kwargs):
        testgen.page_header(
            "Project Overview",
            "introduction-to-dataops-testgen",
        )

        project_code = project_code or session.project
        table_groups_df: pd.DataFrame = get_table_groups_summary(project_code)
        render_project_summary(table_groups_df)

        if render_empty_state(project_code):
            return

        table_group_header_col, table_group_filter_col, table_group_sort_col = st.columns([0.6, 0.2, 0.2])
        table_group_header_col.html(f'<h5 style="margin-top: 16px;">Table Groups ({len(table_groups_df.index)})</h5>')
        with table_group_filter_col:
            name_filter = st.text_input(label="Search by table group name")
            table_groups_df = table_groups_df.loc[
                table_groups_df["table_groups_name"].str.contains(name_filter, case=False)
            ]

        with table_group_sort_col:
            table_groups_df["latest_activity_date"] = table_groups_df[
                ["latest_profile_start", "latest_tests_start"]
            ].apply(pd.to_datetime).max(axis=1) # apply is needed to handle missing values
            ascending_fields: list[str] = ["table_groups_name"]
            sort_options  = pd.DataFrame({
                "value": ["table_groups_name", "latest_activity_date"],
                "label": ["Table group name", "Latest activity"],
            })

            sort_by = testgen.select(
                label="Sort by",
                options=sort_options,
                required=True,
                default_value="latest_activity_date",
                display_column="label",
                value_column="value",
            )

            table_groups_df.sort_values(
                by=typing.cast(str, sort_by),
                ascending=sort_by in ascending_fields,
                inplace=True,
                key=lambda column: column.str.lower() if is_string_dtype(column) else column,
            )

        for index, table_group in table_groups_df.iterrows():
            render_table_group_card(table_group, project_code, index)


def render_empty_state(project_code: str) -> bool:
    project_summary_df = project_queries.get_summary_by_code(project_code)
    if project_summary_df["profiling_runs_ct"] or project_summary_df["test_runs_ct"]:
        return False

    label="Your project is empty"
    testgen.whitespace(3)
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


def render_project_summary(table_groups: pd.DataFrame) -> None:
    project_column, _ = st.columns([.5, .5])
    with project_column:
        testgen.whitespace(0.3)
        with testgen.card():
            summary_column, _ = st.columns([.8, .2])
            # TODO: Uncomment and replace with below section when adding the score
            # score_column, summary_column = st.columns([.5, .5])

            # with score_column:
            #     st.caption("Project HIT score")
            #     st.metric(
            #         "Project HIT score",
            #         value=project_score,
            #         delta=project_score_delta or 0,
            #         label_visibility="collapsed",
            #     )

            with summary_column:
                st.caption("Project Summary")
                st.html(f"""<b>{len(table_groups.index)}</b> table groups
                            <br><b>{int(table_groups['latest_tests_suite_ct'].sum())}</b> test suites
                            <br><b>{int(table_groups['latest_tests_ct'].sum())}</b> test definitions
                            """)


@st.fragment
def render_table_group_card(table_group: pd.Series, project_code: str, key: int) -> None:
    with testgen.card(title=table_group["table_groups_name"]) as test_suite_card:

        # Don't remove this
        # For some reason, st.columns do not get completely removed from DOM when used conditionally within a fragment
        # Without this CSS, the "hidden" elements in the expanded state take up space
        testgen.no_flex_gap()

        with test_suite_card.actions:
            expand_toggle = testgen.expander_toggle(key=f"toggle_{key}")

        profile_column, tests_column = st.columns([.5, .5])
        # TODO: Uncomment and replace with below section when adding the score
        # score_column, profile_column, tests_column = st.columns([.2, .35, .45])

        # with score_column:
        #     st.caption("HIT score")
        #     st.metric(
        #         "HIT score",
        #         value=table_group["score"],
        #         delta=table_group["score_delta"] or 0,
        #         label_visibility="collapsed",
        #     )

        with profile_column:
            testgen.no_flex_gap()
            latest_profile_start = table_group["latest_profile_start"]

            stale_message = ""
            if pd.notnull(latest_profile_start) and (profile_days_ago := (datetime.utcnow() - latest_profile_start).days) > STALE_PROFILE_DAYS:
                stale_message = f'<span style="color: var(--red);">({profile_days_ago} days ago)</span>'
            testgen.caption(f"Latest profile {stale_message}")

            if pd.notnull(latest_profile_start):
                testgen.link(
                    label=date_service.get_timezoned_timestamp(st.session_state, latest_profile_start),
                    href="profiling-runs:results",
                    params={ "run_id": str(table_group["latest_profile_id"]) },
                    key=f"overview:keys:go-to-profile:{table_group['latest_profile_id']}",
                )

                anomaly_count = to_int(table_group["latest_anomalies_ct"])
                with st.container():
                    testgen.flex_row_start()
                    testgen.text(f"""
                                 <b>{to_int(table_group['latest_profile_table_ct'])}</b> tables &nbsp;|&nbsp;
                                 <b>{to_int(table_group['latest_profile_column_ct'])}</b> columns &nbsp;|
                                 """)
                    testgen.link(
                        label=f"{anomaly_count} hygiene issues",
                        href="profiling-runs:hygiene",
                        params={ "run_id": str(table_group["latest_profile_id"]) },
                        width=150,
                        key=f"overview:keys:go-to-issues:{table_group['latest_profile_id']}",
                    )

                if anomaly_count:
                    testgen.summary_bar(
                        items=[
                            { "label": "Definite", "value": to_int(table_group["latest_anomalies_definite_ct"]), "color": "red" },
                            { "label": "Likely", "value": to_int(table_group["latest_anomalies_likely_ct"]), "color": "orange" },
                            { "label": "Possible", "value": to_int(table_group["latest_anomalies_possible_ct"]), "color": "yellow" },
                            { "label": "Dismissed", "value": to_int(table_group["latest_anomalies_dismissed_ct"]), "color": "grey" },
                        ],
                        height=12,
                        width=280,
                    )
            else:
                st.markdown("--")

        with tests_column:
            testgen.no_flex_gap()
            st.caption("Latest test results")
            total_tests = to_int(table_group["latest_tests_ct"])
            if total_tests:
                passed_tests = to_int(table_group["latest_tests_passed_ct"])
                testgen.text(f"{truncate(passed_tests * 100 / total_tests)}% passed")
                testgen.text(f"<b>{total_tests}</b> tests in <b>{to_int(table_group['latest_tests_suite_ct'])}</b> test suites", "margin: 12px 0 12px;")

                testgen.summary_bar(
                items=[
                    { "label": "Passed", "value": passed_tests, "color": "green" },
                    { "label": "Warning", "value": to_int(table_group["latest_tests_warning_ct"]), "color": "yellow" },
                    { "label": "Failed", "value": to_int(table_group["latest_tests_failed_ct"]), "color": "red" },
                    { "label": "Error", "value": to_int(table_group["latest_tests_error_ct"]), "color": "brown" },
                    { "label": "Dismissed", "value": to_int(table_group["latest_tests_dismissed_ct"]), "color": "grey" },
                ],
                height=12,
                width=350,
            )
            else:
                st.markdown("--")

        if expand_toggle:
            render_table_group_expanded(table_group["id"], project_code)


def render_table_group_expanded(table_group_id: str, project_code: str) -> None:
    testgen.divider(8, 12)

    column_spec = [0.25, 0.15, 0.15, 0.5]
    suite_column, generation_column, run_column, results_column = st.columns(column_spec)
    suite_column.caption("Test Suite")
    generation_column.caption("Latest Generation")
    run_column.caption("Latest Run")
    results_column.caption("Latest Results")
    testgen.whitespace(1)

    test_suites_df: pd.DataFrame = test_suite_service.get_by_project(project_code, table_group_id)

    for _, suite in test_suites_df.iterrows():
        render_test_suite_item(suite, column_spec)


def render_test_suite_item(test_suite: pd.Series, column_spec: list[int]) -> None:
    suite_column, generation_column, run_column, results_column = st.columns(column_spec)
    with suite_column:
        testgen.no_flex_gap()
        testgen.link(
            label=test_suite["test_suite"],
            href="test-suites:definitions",
            params={ "test_suite_id": str(test_suite["id"]) },
            key=f"overview:keys:go-to-definitions:{test_suite['id']}",
        )
        testgen.caption(f"{to_int(test_suite['test_ct'])} tests", "margin-top: -16px;")

    with generation_column:
        if (latest_generation := test_suite["latest_auto_gen_date"]) and pd.notnull(latest_generation):
            testgen.text(date_service.get_timezoned_timestamp(st.session_state, latest_generation))
        else:
            st.markdown("--")

    with run_column:
        if (latest_run_start := test_suite["latest_run_start"]) and pd.notnull(latest_run_start):
            testgen.link(
                label=date_service.get_timezoned_timestamp(st.session_state, latest_run_start),
                href="test-runs:results",
                params={ "run_id": str(test_suite["latest_run_id"]) },
                key=f"overview:keys:go-to-run:{test_suite['latest_run_id']}",
            )
        else:
            st.markdown("--")

    with results_column:
        if to_int(test_suite["last_run_test_ct"]):
            testgen.summary_bar(
                items=[
                    { "label": "Passed", "value": to_int(test_suite["last_run_passed_ct"]), "color": "green" },
                    { "label": "Warning", "value": to_int(test_suite["last_run_warning_ct"]), "color": "yellow" },
                    { "label": "Failed", "value": to_int(test_suite["last_run_failed_ct"]), "color": "red" },
                    { "label": "Error", "value": to_int(test_suite["last_run_error_ct"]), "color": "brown" },
                    { "label": "Dismissed", "value": to_int(test_suite["last_run_dismissed_ct"]), "color": "grey" },
                ],
                height=8,
                width=200,
            )
        else:
            st.markdown("--")


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
