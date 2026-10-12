"""Cached query proxies for Streamlit UI.

Wraps model query methods with ``@st.cache_data`` so that the model layer
stays free of Streamlit imports.  Non-UI callers (CLI, API, MCP) call the
model methods directly — no caching overhead.

``st.cache_data`` hands back a copy on a hit but the computed value itself on a miss, and for an
entity that is the instance still attached to the run's session. Every getter returns a detached
copy on both, so a value a view sets on a fetched entity, for a preview or a form, never reaches the
database through the session's commit.
"""

from __future__ import annotations

import pickle  # noqa: S403 -- same round trip st.cache_data applies on a hit
from collections.abc import Iterable
from typing import TypeVar
from uuid import UUID

import streamlit as st

from testgen.common.models.connection import Connection, ConnectionMinimal
from testgen.common.models.entity import ENTITY_HASH_FUNCS
from testgen.common.models.profiling_run import ProfilingRun, ProfilingRunMinimal, ProfilingRunSummary
from testgen.common.models.project import Project, ProjectSummary
from testgen.common.models.project_membership import ProjectMembership
from testgen.common.models.scheduler import JobSchedule
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

T = TypeVar("T")


def _detached(value: T) -> T:
    return pickle.loads(pickle.dumps(value))  # noqa: S301 -- round-trips a value this process just built


# -- Project ------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def get_project_summary(project_code: str) -> ProjectSummary | None:
    return _detached(Project.get_summary(project_code))


# -- ProjectMembership --------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_membership_by_user_and_project(user_id: UUID, project_code: str) -> ProjectMembership | None:
    return _detached(ProjectMembership.get_by_user_and_project(user_id, project_code))


@st.cache_data(show_spinner=False)
def get_projects_for_user(user_id: UUID) -> list[str]:
    return _detached(ProjectMembership.get_projects_for_user(user_id))


@st.cache_data(show_spinner=False)
def get_memberships_for_user(user_id: UUID) -> list[ProjectMembership]:
    return _detached(ProjectMembership.get_memberships_for_user(user_id))


@st.cache_data(show_spinner=False)
def get_memberships_for_project(project_code: str) -> list[ProjectMembership]:
    return _detached(ProjectMembership.get_memberships_for_project(project_code))


# -- TestType -----------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_type_summaries(test_type: str | None = None) -> list[TestTypeSummary]:
    clauses = []
    if test_type is not None:
        clauses.append(TestType.test_type == test_type)
    return _detached(list(TestType.select_summary_where(*clauses)))


# -- TestSuite ----------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_suite_summaries(
    project_code: str,
    table_group_id: str | UUID | None = None,
    test_suite_name: str | None = None,
) -> Iterable[TestSuiteSummary]:
    return _detached(TestSuite.select_summary(project_code, table_group_id, test_suite_name))


# -- TestRun ------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_run_summaries(
    project_code: str | None = None,
    table_group_id: str | UUID | None = None,
    test_suite_id: str | int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[TestRunSummary], int]:
    return _detached(TestRun.select_summary(
        project_code=project_code,
        table_group_id=table_group_id,
        test_suite_id=test_suite_id,
        page=page,
        page_size=page_size,
    ))


# -- TableGroup ---------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_table_group_stats(
    project_code: str,
    table_group_id: str | UUID | None = None,
) -> Iterable[TableGroupStats]:
    return _detached(TableGroup.select_stats(project_code, table_group_id))


@st.cache_data(show_spinner=False)
def get_table_group_summaries(
    project_code: str,
    for_dashboard: bool = False,
) -> Iterable[TableGroupSummary]:
    items, _ = TableGroup.select_summary(project_code, for_dashboard=for_dashboard)
    return _detached(items)


# -- ProfilingRun -------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_profiling_run_summaries(
    project_code: str,
    table_group_id: str | UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ProfilingRunSummary], int]:
    return _detached(ProfilingRun.select_summary(project_code, table_group_id, page=page, page_size=page_size))


# -- JobSchedule --------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_monitor_schedule(monitor_suite_id: str | UUID) -> JobSchedule | None:
    return _detached(JobSchedule.get_for_monitor_suite(monitor_suite_id))


# -- Connection ---------------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_connection(identifier: str | int | UUID, *clauses) -> Connection | None:
    return _detached(Connection.get(identifier, *clauses))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_connections_where(*clauses, order_by=None) -> list[Connection]:
    return _detached(list(Connection.select_where(*clauses, order_by=order_by)))


@st.cache_data(show_spinner=False)
def get_connection_minimal(identifier: int) -> ConnectionMinimal | None:
    return _detached(Connection.get_minimal(identifier))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_connections_minimal_where(*clauses, order_by=None) -> list[ConnectionMinimal]:
    if order_by is None:
        return _detached(list(Connection.select_minimal_where(*clauses)))
    return _detached(list(Connection.select_minimal_where(*clauses, order_by=order_by)))


# -- User ---------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_user(identifier: str) -> User | None:
    return _detached(User.get(identifier))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_users_where(*clauses, order_by=None) -> list[User]:
    return _detached(list(User.select_where(*clauses, order_by=order_by)))


# -- TableGroup ---------------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_table_group(identifier: str | UUID, *clauses) -> TableGroup | None:
    return _detached(TableGroup.get(identifier, *clauses))


@st.cache_data(show_spinner=False)
def get_table_group_minimal(identifier: str | UUID) -> TableGroupMinimal | None:
    return _detached(TableGroup.get_minimal(identifier))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_table_groups_minimal_where(*clauses, order_by=None) -> list[TableGroupMinimal]:
    if order_by is None:
        return _detached(list(TableGroup.select_minimal_where(*clauses)))
    return _detached(list(TableGroup.select_minimal_where(*clauses, order_by=order_by)))


# -- TestSuite ----------------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_test_suite(identifier: str | UUID, *clauses) -> TestSuite | None:
    return _detached(TestSuite.get(identifier, *clauses))


@st.cache_data(show_spinner=False)
def get_test_suite_minimal(identifier: int) -> TestSuiteMinimal | None:
    return _detached(TestSuite.get_minimal(identifier))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_suites_minimal_where(*clauses, order_by=None) -> list[TestSuiteMinimal]:
    if order_by is None:
        return _detached(list(TestSuite.select_minimal_where(*clauses)))
    return _detached(list(TestSuite.select_minimal_where(*clauses, order_by=order_by)))


# -- TestRun ------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_run_minimal(run_id: str | UUID) -> TestRunMinimal | None:
    return _detached(TestRun.get_minimal(run_id))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_runs_where(*clauses, order_by=None) -> list[TestRun]:
    return _detached(list(TestRun.select_where(*clauses, order_by=order_by)))


# -- ProfilingRun -------------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_profiling_run_minimal(run_id: str | UUID) -> ProfilingRunMinimal | None:
    return _detached(ProfilingRun.get_minimal(run_id))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_profiling_runs_where(*clauses, order_by=None) -> list[ProfilingRun]:
    return _detached(list(ProfilingRun.select_where(*clauses, order_by=order_by)))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_profiling_runs_minimal_where(*clauses, order_by=None) -> list[ProfilingRunMinimal]:
    if order_by is None:
        return _detached(list(ProfilingRun.select_minimal_where(*clauses)))
    return _detached(list(ProfilingRun.select_minimal_where(*clauses, order_by=order_by)))


# -- TestDefinition -----------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_test_definition(identifier: str | UUID) -> TestDefinitionSummary | None:
    return _detached(TestDefinition.get(identifier))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_definitions_where(*clauses, order_by=None) -> list[TestDefinitionSummary]:
    if order_by is None:
        return _detached(list(TestDefinition.select_where(*clauses)))
    return _detached(list(TestDefinition.select_where(*clauses, order_by=order_by)))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_definitions_minimal_where(*clauses, order_by=None) -> list[TestDefinitionMinimal]:
    if order_by is None:
        return _detached(list(TestDefinition.select_minimal_where(*clauses)))
    return _detached(list(TestDefinition.select_minimal_where(*clauses, order_by=order_by)))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_test_definitions_page(
    *clauses,
    order_by=None,
    page: int = 1,
    limit: int = 500,
) -> tuple[list[TestDefinitionSummary], int]:
    return _detached(TestDefinition.select_page(*clauses, order_by=order_by, page=page, limit=limit))


# -- Project ------------------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_project(identifier: str, *clauses) -> Project | None:
    return _detached(Project.get(identifier, *clauses))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_projects_where(*clauses, order_by=None) -> list[Project]:
    return _detached(list(Project.select_where(*clauses, order_by=order_by)))


# -- ProjectMembership --------------------------------------------------------

@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def get_project_membership(identifier: str | UUID, *clauses) -> ProjectMembership | None:
    return _detached(ProjectMembership.get(identifier, *clauses))


@st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
def select_project_memberships_where(*clauses, order_by=None) -> list[ProjectMembership]:
    return _detached(list(ProjectMembership.select_where(*clauses, order_by=order_by)))
