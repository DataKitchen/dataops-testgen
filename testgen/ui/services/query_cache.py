"""Cached query proxies for Streamlit UI.

Wraps model query methods with ``@st.cache_data`` so that the model layer
stays free of Streamlit imports.  Non-UI callers (CLI, API, MCP) call the
model methods directly — no caching overhead.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

import streamlit as st

from testgen.common.models.connection import Connection
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunSummary
from testgen.common.models.project import Project, ProjectSummary
from testgen.common.models.project_membership import ProjectMembership
from testgen.common.models.table_group import TableGroup, TableGroupStats, TableGroupSummary
from testgen.common.models.test_definition import TestType, TestTypeSummary
from testgen.common.models.test_run import TestRun, TestRunSummary
from testgen.common.models.test_suite import TestSuite, TestSuiteSummary

# -- Project ------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_project_summary(project_code: str) -> ProjectSummary | None:
    return Project.get_summary(project_code)


# -- ProjectMembership --------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_membership_by_user_and_project(user_id: UUID, project_code: str) -> ProjectMembership | None:
    return ProjectMembership.get_by_user_and_project(user_id, project_code)


@st.cache_data(show_spinner=False)
def get_projects_for_user(user_id: UUID) -> list[str]:
    return ProjectMembership.get_projects_for_user(user_id)


@st.cache_data(show_spinner=False)
def get_memberships_for_user(user_id: UUID) -> list[ProjectMembership]:
    return ProjectMembership.get_memberships_for_user(user_id)


@st.cache_data(show_spinner=False)
def get_memberships_for_project(project_code: str) -> list[ProjectMembership]:
    return ProjectMembership.get_memberships_for_project(project_code)


# -- Connection ---------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_connection_by_table_group(table_group_id: str | UUID) -> Connection | None:
    return Connection.get_by_table_group(table_group_id)


# -- TestType -----------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_type_summaries(test_type: str | None = None) -> list[TestTypeSummary]:
    clauses = []
    if test_type is not None:
        clauses.append(TestType.test_type == test_type)
    return list(TestType.select_summary_where(*clauses))


# -- TestSuite ----------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_suite_summaries(
    project_code: str,
    table_group_id: str | UUID | None = None,
    test_suite_name: str | None = None,
) -> Iterable[TestSuiteSummary]:
    return TestSuite.select_summary(project_code, table_group_id, test_suite_name)


# -- TestRun ------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_run_summaries(
    project_code: str | None = None,
    table_group_id: str | UUID | None = None,
    test_suite_id: str | int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[TestRunSummary], int]:
    return TestRun.select_summary(
        project_code=project_code,
        table_group_id=table_group_id,
        test_suite_id=test_suite_id,
        page=page,
        page_size=page_size,
    )


# -- TableGroup ---------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_table_group_stats(
    project_code: str,
    table_group_id: str | UUID | None = None,
) -> Iterable[TableGroupStats]:
    return TableGroup.select_stats(project_code, table_group_id)


@st.cache_data(show_spinner=False)
def get_table_group_summaries(
    project_code: str,
    for_dashboard: bool = False,
) -> Iterable[TableGroupSummary]:
    return TableGroup.select_summary(project_code, for_dashboard)


# -- ProfilingRun -------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_profiling_run_summaries(
    project_code: str,
    table_group_id: str | UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ProfilingRunSummary], int]:
    return ProfilingRun.select_summary(project_code, table_group_id, page=page, page_size=page_size)
