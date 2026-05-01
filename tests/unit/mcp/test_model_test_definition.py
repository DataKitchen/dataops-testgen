from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.test_definition import TestDefinition


@pytest.fixture
def session_mock():
    with (
        patch("testgen.common.models.test_definition.get_current_session") as td_mock,
        patch("testgen.common.models.entity.get_current_session") as entity_mock,
    ):
        entity_mock.return_value = td_mock.return_value
        yield td_mock.return_value


def _compiled_sql(captured_query) -> str:
    return str(captured_query.compile(dialect=postgresql.dialect()))


def test_get_for_project_excludes_monitor_suites(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = None

    TestDefinition.get_for_project(uuid4())

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "test_suites.is_monitor IS NOT true" in sql
    assert "JOIN test_suites" in sql


def test_get_for_project_excludes_monitor_suites_with_project_codes(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = None

    TestDefinition.get_for_project(uuid4(), project_codes=["demo"])

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "test_suites.is_monitor IS NOT true" in sql
    assert "test_suites.project_code IN" in sql


def test_list_for_suite_excludes_monitor_suites(session_mock):
    session_mock.scalar.return_value = 0
    session_mock.execute.return_value.all.return_value = []

    TestDefinition.list_for_suite(test_suite_id=uuid4())

    # _paginate wraps the original query as a subquery for counting — the is_monitor
    # filter is preserved in the compiled SQL for either call, so check both.
    queries = [call[0][0] for call in session_mock.scalar.call_args_list]
    queries += [call[0][0] for call in session_mock.execute.call_args_list]
    sql_joined = "\n".join(_compiled_sql(q) for q in queries)
    assert "test_suites.is_monitor IS NOT true" in sql_joined
    assert "JOIN test_suites" in sql_joined
