"""Wiring tests for query_cache.py wrappers.

Verifies that each cached UI wrapper exists, is callable, and exposes ``.clear()``
for targeted cache invalidation. Does NOT exercise Streamlit cache logic itself.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, object_session

from testgen.common.models.table_group import TableGroup
from testgen.ui.services import query_cache

# Wrappers that replace cached calls to model methods after TG-1091.
# Names match the per-(entity, method) convention documented in the spec.
EXPECTED_WRAPPERS = [
    # Connection
    "get_connection",
    "select_connections_where",
    "get_connection_minimal",
    "select_connections_minimal_where",
    # User
    "get_user",
    "select_users_where",
    # TableGroup
    "get_table_group",
    "get_table_group_minimal",
    "select_table_groups_minimal_where",
    # TestSuite
    "get_test_suite",
    "get_test_suite_minimal",
    "select_test_suites_minimal_where",
    # TestRun
    "get_test_run_minimal",
    "select_test_runs_where",
    # ProfilingRun
    "get_profiling_run_minimal",
    "select_profiling_runs_where",
    "select_profiling_runs_minimal_where",
    # TestDefinition
    "get_test_definition",
    "select_test_definitions_where",
    "select_test_definitions_minimal_where",
    "select_test_definitions_page",
    # Project
    "get_project",
    "select_projects_where",
    # ProjectMembership
    "get_project_membership",
    "select_project_memberships_where",
]


@pytest.mark.parametrize("name", EXPECTED_WRAPPERS)
def test_wrapper_exists_and_is_cached(name: str) -> None:
    wrapper = getattr(query_cache, name, None)
    assert wrapper is not None, f"Missing wrapper: query_cache.{name}"
    assert callable(wrapper), f"Wrapper is not callable: query_cache.{name}"
    assert hasattr(wrapper, "clear"), (
        f"Wrapper missing .clear() (cache decorator dropped?): query_cache.{name}"
    )


def test_a_fetched_entity_is_detached_even_on_a_cache_miss() -> None:
    """A preview sets unsaved form values on the entity it fetched, and the run's session commits.

    ``st.cache_data`` returns a copy on a hit but the computed value on a miss, so without the
    getter's own copy a miss would hand back the session's instance and commit those values.
    """
    session = Session()
    stored = TableGroup(id=uuid4(), table_groups_name="orders", table_group_schema="sales")
    session.add(stored)

    query_cache.get_table_group.clear()
    with patch.object(TableGroup, "get", return_value=stored):
        fetched = query_cache.get_table_group(str(stored.id))

    fetched.table_group_schema = "sales_v2"

    assert fetched is not stored
    assert object_session(fetched) is None
    assert stored.table_group_schema == "sales"
