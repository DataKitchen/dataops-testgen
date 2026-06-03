"""Cached query proxies for Streamlit UI.

Wraps model query methods with ``@st.cache_data`` so that the model layer
stays free of Streamlit imports.  Non-UI callers (CLI, API, MCP) call the
model methods directly — no caching overhead.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

import streamlit as st

from testgen.common.models.connection import Connection, ConnectionMinimal
from testgen.common.models.entity import ENTITY_HASH_FUNCS
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunMinimal, ProfilingRunSummary
from testgen.common.models.project import Project, ProjectSummary
from testgen.common.models.project_membership import ProjectMembership
from testgen.common.models.scheduler import RUN_MONITORS_JOB_KEY, JobSchedule
from testgen.common.models.table_group import (
    TableGroup,
    TableGroupMinimal,
    TableGroupStats,
    TableGroupSummary,
)
from testgen.common.models.test_definition import (
    TestDefinition,
    TestDefinitionMinimal,
    TestDefinitionSummary,
    TestType,
    TestTypeSummary,
)
from testgen.common.models.test_run import TestRun, TestRunMinimal, TestRunSummary
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal, TestSuiteSummary
from testgen.common.models.user import User

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
    items, _ = TableGroup.select_summary(project_code, for_dashboard=for_dashboard)
    return items


# -- ProfilingRun -------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_profiling_run_summaries(
    project_code: str,
    table_group_id: str | UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ProfilingRunSummary], int]:
    return ProfilingRun.select_summary(project_code, table_group_id, page=page, page_size=page_size)


# -- JobSchedule --------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_monitor_schedule(monitor_suite_id: str | UUID) -> JobSchedule | None:
    return JobSchedule.get(
        JobSchedule.key == RUN_MONITORS_JOB_KEY,
        JobSchedule.kwargs["test_suite_id"].astext == str(monitor_suite_id),
    )


# -- Connection ---------------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_connection(identifier: str | int | UUID, *clauses) -> Connection | None:
    return Connection.get(identifier, *clauses)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_connections_where(*clauses, order_by=None) -> list[Connection]:
    return list(Connection.select_where(*clauses, order_by=order_by))


@st.cache_data(show_spinner=False)
def get_connection_minimal(identifier: int) -> ConnectionMinimal | None:
    return Connection.get_minimal(identifier)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_connections_minimal_where(*clauses, order_by=None) -> list[ConnectionMinimal]:
    if order_by is None:
        return list(Connection.select_minimal_where(*clauses))
    return list(Connection.select_minimal_where(*clauses, order_by=order_by))


# -- User ---------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_user(identifier: str) -> User | None:
    return User.get(identifier)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_users_where(*clauses, order_by=None) -> list[User]:
    return list(User.select_where(*clauses, order_by=order_by))


# -- TableGroup ---------------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_table_group(identifier: str | UUID, *clauses) -> TableGroup | None:
    return TableGroup.get(identifier, *clauses)


@st.cache_data(show_spinner=False)
def get_table_group_minimal(identifier: str | UUID) -> TableGroupMinimal | None:
    return TableGroup.get_minimal(identifier)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_table_groups_minimal_where(*clauses, order_by=None) -> list[TableGroupMinimal]:
    if order_by is None:
        return list(TableGroup.select_minimal_where(*clauses))
    return list(TableGroup.select_minimal_where(*clauses, order_by=order_by))


# -- TestSuite ----------------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_test_suite(identifier: str | UUID, *clauses) -> TestSuite | None:
    return TestSuite.get(identifier, *clauses)


@st.cache_data(show_spinner=False)
def get_test_suite_minimal(identifier: int) -> TestSuiteMinimal | None:
    return TestSuite.get_minimal(identifier)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_suites_minimal_where(*clauses, order_by=None) -> list[TestSuiteMinimal]:
    if order_by is None:
        return list(TestSuite.select_minimal_where(*clauses))
    return list(TestSuite.select_minimal_where(*clauses, order_by=order_by))


# -- TestRun ------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_run_minimal(run_id: str | UUID) -> TestRunMinimal | None:
    return TestRun.get_minimal(run_id)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_runs_where(*clauses, order_by=None) -> list[TestRun]:
    return list(TestRun.select_where(*clauses, order_by=order_by))


# -- ProfilingRun -------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_profiling_run_minimal(run_id: str | UUID) -> ProfilingRunMinimal | None:
    return ProfilingRun.get_minimal(run_id)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_profiling_runs_where(*clauses, order_by=None) -> list[ProfilingRun]:
    return list(ProfilingRun.select_where(*clauses, order_by=order_by))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_profiling_runs_minimal_where(*clauses, order_by=None) -> list[ProfilingRunMinimal]:
    if order_by is None:
        return list(ProfilingRun.select_minimal_where(*clauses))
    return list(ProfilingRun.select_minimal_where(*clauses, order_by=order_by))


# -- TestDefinition -----------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_definition(identifier: str | UUID) -> TestDefinitionSummary | None:
    return TestDefinition.get(identifier)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_definitions_where(*clauses, order_by=None) -> list[TestDefinitionSummary]:
    if order_by is None:
        return list(TestDefinition.select_where(*clauses))
    return list(TestDefinition.select_where(*clauses, order_by=order_by))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_definitions_minimal_where(*clauses, order_by=None) -> list[TestDefinitionMinimal]:
    if order_by is None:
        return list(TestDefinition.select_minimal_where(*clauses))
    return list(TestDefinition.select_minimal_where(*clauses, order_by=order_by))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_definitions_page(
    *clauses,
    order_by=None,
    page: int = 1,
    limit: int = 500,
) -> tuple[list[TestDefinitionSummary], int]:
    return TestDefinition.select_page(*clauses, order_by=order_by, page=page, limit=limit)


# -- Project ------------------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_project(identifier: str, *clauses) -> Project | None:
    return Project.get(identifier, *clauses)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_projects_where(*clauses, order_by=None) -> list[Project]:
    return list(Project.select_where(*clauses, order_by=order_by))


# -- ProjectMembership --------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_project_membership(identifier: str | UUID, *clauses) -> ProjectMembership | None:
    return ProjectMembership.get(identifier, *clauses)


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_project_memberships_where(*clauses, order_by=None) -> list[ProjectMembership]:
    return list(ProjectMembership.select_where(*clauses, order_by=order_by))
