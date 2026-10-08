"""Tests for running monitor generation in the caller's session."""

from unittest.mock import MagicMock, patch

import pytest

from testgen.commands.test_generation import TestGeneration, run_monitor_generation
from testgen.common.enums import SuiteType

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.test_generation"
QUERIES = [("INSERT INTO test_definitions SELECT 1", {"A": 1}), ("UPDATE test_definitions SET x = 1", {"B": 2})]


def _generation() -> TestGeneration:
    generation = TestGeneration.__new__(TestGeneration)
    generation._get_generation_queries = MagicMock(return_value=QUERIES)
    return generation


@patch(f"{MODULE}.execute_db_queries")
@patch(f"{MODULE}.get_current_session")
def test_monitor_run_in_session_executes_through_the_session(mock_session, mock_execute):
    _generation().monitor_run("upsert", in_session=True)

    executed = [(str(call.args[0]), call.args[1]) for call in mock_session.return_value.execute.call_args_list]
    assert executed == QUERIES
    mock_session.return_value.commit.assert_not_called()
    mock_execute.assert_not_called()


@patch(f"{MODULE}.execute_db_queries")
@patch(f"{MODULE}.get_current_session")
def test_monitor_run_by_default_uses_its_own_connection(mock_session, mock_execute):
    _generation().monitor_run("upsert")

    mock_execute.assert_called_once_with(QUERIES)
    mock_session.return_value.execute.assert_not_called()


@patch(f"{MODULE}.TestGeneration")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.TestSuite")
def test_run_monitor_generation_passes_in_session_through(mock_suite_cls, _tg, _conn, mock_generation_cls):
    mock_suite_cls.get.return_value = MagicMock(suite_type=SuiteType.MONITOR)

    run_monitor_generation("suite-id", ["Volume_Trend"], in_session=True)

    mock_generation_cls.return_value.monitor_run.assert_called_once_with("upsert", table_names=None, in_session=True)
