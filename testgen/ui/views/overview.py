import typing
from datetime import datetime

import pandas as pd
import streamlit as st

import testgen.ui.services.database_service as db
from testgen.common import date_service
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import test_suite_service
from testgen.ui.session import session

STALE_PROFILE_DAYS = 30


class OverviewPage(Page):
    path = "overview"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
    ]
    menu_item = MenuItem(icon="home", label="Overview", order=0)

    def render(self, project_code: str | None = None, **_kwargs):
        project_code = project_code or session.project
        table_groups_df: pd.DataFrame = get_table_groups_summary(project_code)

        testgen.page_header(
            "Project Overview",
            "https://docs.datakitchen.io/article/dataops-testgen-help/introduction-to-dataops-testgen",
        )  
        
        render_project_summary(table_groups_df)

        st.html(f'<h5 style="margin-top: 16px;">Table Groups ({len(table_groups_df.index)})</h5>')
        for index, table_group in table_groups_df.iterrows():
            render_table_group_card(table_group, project_code, index)


def render_project_summary(table_groups: pd.DataFrame) -> None:
    project_column, _ = st.columns([.5, .5])
    with project_column:
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
            profile_days_ago = (datetime.utcnow() - table_group["latest_profile_start"]).days
            st.html(f"""<p class="caption">Latest profile {f'<span style="color: var(--error-color);">({profile_days_ago} days ago)</span>' if profile_days_ago > STALE_PROFILE_DAYS else ""}</p>""")

            if (latest_profile_id := table_group["latest_profile_id"]) and not pd.isnull(latest_profile_id):
                testgen.link(
                    label=date_service.get_timezoned_timestamp(st.session_state, table_group["latest_profile_start"]),
                    href="profiling-runs:results",
                    params={ "run_id": str(latest_profile_id) },
                    key=f"overview:keys:go-to-profile:{latest_profile_id}",
                )
                
                st.html(f"""
                            <b>{int(table_group["latest_anomalies_ct"])}</b> anomalies in <b>{int(table_group["latest_profile_table_ct"])}</b> tables
                            """)

                testgen.summary_bar(
                    items=[
                        { "label": "Definite", "value": int(table_group["latest_anomalies_definite_ct"]), "color": "red" },
                        { "label": "Likely", "value": int(table_group["latest_anomalies_likely_ct"]), "color": "orange" },
                        { "label": "Possible", "value": int(table_group["latest_anomalies_possible_ct"]), "color": "yellow" },
                        { "label": "Dismissed", "value": int(table_group["latest_anomalies_dismissed_ct"]), "color": "grey" },
                    ],
                    key=f"anomalies_{key}",
                    height=12,
                    width=280,
                )
            else:
                st.markdown("--")

        with tests_column:
            testgen.no_flex_gap()
            st.caption("Latest test results")
            total_tests = int(table_group["latest_tests_ct"]) if not pd.isnull(table_group["latest_tests_ct"]) else 0
            if total_tests:
                passed_tests = int(table_group["latest_tests_passed_ct"])
                
                st.html(f"""
                            <p style="margin: -6px 0 8px;">{round(passed_tests * 100 / total_tests)}% passed</p>
                            <b>{total_tests}</b> tests in <b>{int(table_group["latest_tests_suite_ct"])}</b> test suites
                            """)
                
                testgen.summary_bar(
                items=[
                    { "label": "Passed", "value": passed_tests, "color": "green" },
                    { "label": "Warnings", "value": int(table_group["latest_tests_warning_ct"]), "color": "yellow" },
                    { "label": "Failed", "value": int(table_group["latest_tests_failed_ct"]), "color": "red" },
                    { "label": "Errors", "value": int(table_group["latest_tests_error_ct"]), "color": "brown" },
                    { "label": "Dismissed", "value": int(table_group["latest_tests_dismissed_ct"]), "color": "grey" },
                ],
                key=f"tests_{key}",
                height=12,
                width=350,
            )
            else:
                st.markdown("--")

        if expand_toggle:
            render_table_group_expanded(table_group["id"], project_code, key)
            

def render_table_group_expanded(table_group_id: str, project_code: str, key: int) -> None:
    st.html('<hr style="margin: 8px 0 12px;">')

    column_spec = [0.25, 0.15, 0.15, 0.5]
    suite_column, generation_column, run_column, results_column = st.columns(column_spec)
    suite_column.caption("Test Suite")
    generation_column.caption("Latest Generation")
    run_column.caption("Latest Run")
    results_column.caption("Latest Results")
    testgen.whitespace(1)

    test_suites_df: pd.DataFrame = test_suite_service.get_by_project(project_code, table_group_id)

    for index, suite in test_suites_df.iterrows():
        render_test_suite_item(suite, column_spec, f"{key}_{index}")


def render_test_suite_item(test_suite: pd.Series, column_spec: list[int], key: int) -> None:
    suite_column, generation_column, run_column, results_column = st.columns(column_spec)
    with suite_column:
        testgen.no_flex_gap()
        testgen.link(
            label=test_suite["test_suite"],
            href="test-suites:definitions",
            params={ "test_suite_id": str(test_suite["id"]) },
            key=f"overview:keys:go-to-definitions:{test_suite['id']}",
        )
        st.html(f'<p class="caption" style="margin-top: -16px;">{test_suite["last_run_test_ct"]} tests</p>')

    if (latest_generation := test_suite["latest_auto_gen_date"]) and not pd.isnull(latest_generation):
        generation_column.html(f'<p class="line">{date_service.get_timezoned_timestamp(st.session_state, latest_generation)}</p>')
    else:
        generation_column.markdown("--")

    latest_run_id = test_suite["latest_run_id"]
    if latest_run_id and not pd.isnull(latest_run_id):
        with run_column:
            testgen.link(
                label=date_service.get_timezoned_timestamp(st.session_state, test_suite["latest_run_start"]),
                href="test-runs:results",
                params={ "run_id": str(latest_run_id) },
                key=f"overview:keys:go-to-run:{latest_run_id}",
            )

        with results_column:
            testgen.summary_bar(
                items=[
                    { "label": "Passed", "value": int(test_suite["last_run_passed_ct"]), "color": "green" },
                    { "label": "Warnings", "value": int(test_suite["last_run_warning_ct"]), "color": "yellow" },
                    { "label": "Failed", "value": int(test_suite["last_run_failed_ct"]), "color": "red" },
                    { "label": "Errors", "value": int(test_suite["last_run_error_ct"]), "color": "brown" },
                    { "label": "Dismissed", "value": int(test_suite["last_run_dismissed_ct"]), "color": "grey" },
                ],
                key=f"tests_{key}",
                height=8,
                width=200,
            )
    else:
        run_column.markdown("--")
        results_column.html("--<br><br>")


def get_table_groups_summary(project_code: str) -> pd.DataFrame:
    schema = st.session_state["dbschema"]
    sql = f"""
    WITH latest_profile_dates AS (
        SELECT table_groups_id,
            MAX(profiling_starttime) as profiling_starttime
        FROM {schema}.profiling_runs
        GROUP BY table_groups_id
    ),
    latest_profile AS (
        SELECT latest_run.table_groups_id,
            latest_run.id,
            latest_run.profiling_starttime,
            latest_run.table_ct,
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
        FROM latest_profile_dates lpd
            LEFT JOIN {schema}.profiling_runs latest_run ON (
                lpd.table_groups_id = latest_run.table_groups_id
                AND lpd.profiling_starttime = latest_run.profiling_starttime
            )
            LEFT JOIN {schema}.profile_anomaly_results latest_anomalies ON (
                latest_run.id = latest_anomalies.profile_run_id
            )
            LEFT JOIN {schema}.profile_anomaly_types anomaly_types ON (
                anomaly_types.id = latest_anomalies.anomaly_id
            )
        GROUP BY latest_run.id
    ),
    latest_run_dates AS (
        SELECT test_suite_id,
            MAX(test_starttime) as test_starttime
        FROM {schema}.test_runs
        GROUP BY test_suite_id
    ),
    latest_tests AS (
        SELECT suites.table_groups_id,
            COUNT(DISTINCT latest_run.test_suite_id) as test_suite_ct,
            COUNT(*) as test_ct,
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
        FROM latest_run_dates lrd
            LEFT JOIN {schema}.test_runs latest_run ON (
                lrd.test_suite_id = latest_run.test_suite_id
                AND lrd.test_starttime = latest_run.test_starttime
            )
            LEFT JOIN {schema}.test_results latest_results ON (
                latest_run.id = latest_results.test_run_id
            )
            LEFT JOIN {schema}.test_suites as suites ON (suites.id = lrd.test_suite_id)
        GROUP BY suites.table_groups_id
    )
    SELECT groups.id::VARCHAR(50),
        groups.table_groups_name,
        latest_profile.id as latest_profile_id,
        latest_profile.profiling_starttime as latest_profile_start,
        latest_profile.table_ct as latest_profile_table_ct,
        latest_profile.anomaly_ct as latest_anomalies_ct,
        latest_profile.definite_ct as latest_anomalies_definite_ct,
        latest_profile.likely_ct as latest_anomalies_likely_ct,
        latest_profile.possible_ct as latest_anomalies_possible_ct,
        latest_profile.dismissed_ct as latest_anomalies_dismissed_ct,
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
