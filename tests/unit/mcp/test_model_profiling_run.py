from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.profiling_run import ProfilingRun


@pytest.fixture
def session_mock():
    with patch("testgen.common.models.profiling_run.get_current_session") as mock:
        yield mock.return_value


def _compiled_sql(captured_query) -> str:
    return str(captured_query.compile(dialect=postgresql.dialect()))


def test_get_latest_complete_je_id_returns_je_id_when_present(session_mock):
    je_id = uuid4()
    session_mock.scalar.return_value = je_id

    result = ProfilingRun.get_latest_complete_je_id_for_table_group(uuid4())

    assert result == je_id


def test_get_latest_complete_je_id_returns_none_when_no_runs(session_mock):
    session_mock.scalar.return_value = None

    result = ProfilingRun.get_latest_complete_je_id_for_table_group(uuid4())

    assert result is None


def test_get_latest_complete_je_id_filters_to_completed(session_mock):
    session_mock.scalar.return_value = None

    ProfilingRun.get_latest_complete_je_id_for_table_group(uuid4())

    sql = _compiled_sql(session_mock.scalar.call_args[0][0])
    assert "job_executions.status =" in sql


def test_get_latest_complete_je_id_orders_desc_limit_1(session_mock):
    session_mock.scalar.return_value = None

    ProfilingRun.get_latest_complete_je_id_for_table_group(uuid4())

    sql = _compiled_sql(session_mock.scalar.call_args[0][0])
    assert "ORDER BY job_executions.started_at DESC" in sql
    assert "LIMIT" in sql


def test_get_latest_complete_je_id_selects_je_id_not_run_pk(session_mock):
    """Pin the docstring contract — does NOT read ``table_groups.last_complete_profile_run_id``,
    selects the JE id directly from ``profiling_runs``."""
    session_mock.scalar.return_value = None

    ProfilingRun.get_latest_complete_je_id_for_table_group(uuid4())

    sql = _compiled_sql(session_mock.scalar.call_args[0][0])
    assert "SELECT profiling_runs.job_execution_id" in sql
    assert "table_groups.last_complete_profile_run_id" not in sql
