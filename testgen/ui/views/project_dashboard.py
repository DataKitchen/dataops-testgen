import typing

import streamlit as st

from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.session import session
from testgen.utils import friendly_score, make_json_safe, score

PAGE_TITLE = "Project Dashboard"
PAGE_ICON = "home"


class ProjectDashboardPage(Page):
    path = "project-dashboard"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        order=0,
    )

    def render(self, project_code: str, **_kwargs):
        testgen.page_header(
            PAGE_TITLE,
        )

        with st.spinner("Loading data ..."):
            table_groups = TableGroup.select_summary(project_code, for_dashboard=True)
            test_suites = TestSuite.select_summary(project_code)
            project_summary = Project.get_summary(project_code)

        table_groups_sort = st.session_state.get("overview_table_groups_sort") or "latest_activity_date"

        testgen.testgen_component(
            "project_dashboard",
            props={
                "project_summary": project_summary.to_dict(json_safe=True),
                "table_groups": [
                    {
                        **table_group.to_dict(json_safe=True),
                        "test_suites": [
                            test_suite.to_dict(json_safe=True)
                            for test_suite in test_suites
                            if test_suite.table_groups_id == table_group.id
                        ],
                        "latest_tests_start": make_json_safe(
                            max(
                                (
                                    test_suite.latest_run_start
                                    for test_suite in test_suites
                                    if test_suite.table_groups_id == table_group.id
                                    and test_suite.latest_run_start
                                ),
                                default=None,
                            )
                        ),
                        "dq_score": friendly_score(score(table_group.dq_score_profiling, table_group.dq_score_testing)),
                        "dq_score_profiling": friendly_score(table_group.dq_score_profiling),
                        "dq_score_testing": friendly_score(table_group.dq_score_testing),
                        "monitoring_summary": {
                            "project_code": project_code,
                            "table_group_id": str(table_group.id),
                            "lookback": table_group.monitor_lookback,
                            "lookback_start": make_json_safe(table_group.monitor_lookback_start),
                            "lookback_end": make_json_safe(table_group.monitor_lookback_end),
                            "freshness_anomalies": table_group.monitor_freshness_anomalies or 0,
                            "schema_anomalies": table_group.monitor_schema_anomalies or 0,
                            "volume_anomalies": table_group.monitor_volume_anomalies or 0,
                            "metric_anomalies": table_group.monitor_metric_anomalies or 0,
                            "freshness_has_errors": table_group.monitor_freshness_has_errors or False,
                            "volume_has_errors": table_group.monitor_volume_has_errors or False,
                            "schema_has_errors": table_group.monitor_schema_has_errors or False,
                            "metric_has_errors": table_group.monitor_metric_has_errors or False,
                            "freshness_is_training": table_group.monitor_freshness_is_training or False,
                            "volume_is_training": table_group.monitor_volume_is_training or False,
                            "metric_is_training": table_group.monitor_metric_is_training or False,
                            "freshness_is_pending": table_group.monitor_freshness_is_pending or False,
                            "volume_is_pending": table_group.monitor_volume_is_pending or False,
                            "schema_is_pending": table_group.monitor_schema_is_pending or False,
                            "metric_is_pending": table_group.monitor_metric_is_pending or False,
                        } if table_group.monitor_test_suite_id else None,
                    }
                    for table_group in table_groups
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
        )
