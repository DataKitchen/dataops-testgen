import typing

import streamlit as st

from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.services import user_session_service
from testgen.ui.session import session
from testgen.utils import friendly_score, make_json_safe, score

PAGE_TITLE = "Project Dashboard"
PAGE_ICON = "home"


class ProjectDashboardPage(Page):
    path = "project-dashboard"
    can_activate: typing.ClassVar = [
        lambda: session.authentication_status,
        lambda: not user_session_service.user_has_catalog_role(),
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        order=0,
        roles=[ role for role in typing.get_args(user_session_service.RoleType) if role != "catalog" ],
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
