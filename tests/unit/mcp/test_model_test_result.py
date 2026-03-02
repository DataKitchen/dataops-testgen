from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.test_result import TestResult, TestResultStatus


@pytest.fixture
def session_mock():
    with patch("testgen.common.models.test_result.get_current_session") as mock:
        yield mock.return_value


def test_select_results_basic(session_mock):
    mock_results = [MagicMock(spec=TestResult)]
    session_mock.scalars.return_value.all.return_value = mock_results

    results = TestResult.select_results(test_run_id=uuid4())

    assert results == mock_results
    session_mock.scalars.assert_called_once()


def test_select_results_with_status_filter(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    results = TestResult.select_results(test_run_id=uuid4(), status=TestResultStatus.Failed)

    assert results == []


def test_select_results_with_all_filters(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    results = TestResult.select_results(
        test_run_id=uuid4(),
        status=TestResultStatus.Passed,
        table_name="orders",
        test_type="Alpha_Trunc",
        limit=10,
    )

    assert results == []


def test_select_failures_by_test_type(session_mock):
    session_mock.execute.return_value.all.return_value = [
        ("Alpha_Trunc", TestResultStatus.Failed, 5),
        ("Unique_Pct", TestResultStatus.Warning, 3),
    ]

    results = TestResult.select_failures(test_run_id=uuid4(), group_by="test_type")

    assert len(results) == 2
    assert results[0] == ("Alpha_Trunc", TestResultStatus.Failed, 5)


def test_select_failures_by_table_name(session_mock):
    session_mock.execute.return_value.all.return_value = [("orders", 8)]

    results = TestResult.select_failures(test_run_id=uuid4(), group_by="table_name")

    assert results[0] == ("orders", 8)


def test_select_failures_by_column_names(session_mock):
    session_mock.execute.return_value.all.return_value = [("orders", "customer_name", 4)]

    results = TestResult.select_failures(test_run_id=uuid4(), group_by="column_names")

    assert results[0] == ("orders", "customer_name", 4)


def test_select_failures_invalid_group_by():
    with pytest.raises(ValueError, match="group_by must be one of"):
        TestResult.select_failures(test_run_id=uuid4(), group_by="invalid_column")


def test_select_failures_empty(session_mock):
    session_mock.execute.return_value.all.return_value = []

    results = TestResult.select_failures(test_run_id=uuid4())

    assert results == []


def test_select_history_basic(session_mock):
    mock_results = [MagicMock(spec=TestResult), MagicMock(spec=TestResult)]
    session_mock.scalars.return_value.all.return_value = mock_results

    results = TestResult.select_history(test_definition_id=uuid4())

    assert results == mock_results
    session_mock.scalars.assert_called_once()


def test_select_history_empty(session_mock):
    session_mock.scalars.return_value.all.return_value = []

    results = TestResult.select_history(test_definition_id=uuid4(), limit=10)

    assert results == []
