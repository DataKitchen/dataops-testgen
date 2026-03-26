from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_session():
    """Mock the session layer so database_session context manager can run."""
    session = MagicMock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    with patch("testgen.common.models.Session", return_value=session):
        yield session


def test_run_profiling_in_background_submits(mock_session):
    table_group_id = uuid4()
    mock_tg = MagicMock()
    mock_tg.project_code = "DEFAULT"

    with patch("testgen.common.models.table_group.TableGroup.get", return_value=mock_tg):
        from testgen.commands.run_profiling import run_profiling_in_background
        run_profiling_in_background(table_group_id)

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.job_key == "run-profile"
    assert added.kwargs == {"table_group_id": str(table_group_id)}
    assert added.source == "ui"
    assert added.project_code == "DEFAULT"
    mock_session.commit.assert_called_once()


def test_run_test_execution_in_background_submits(mock_session):
    test_suite_id = uuid4()
    mock_ts = MagicMock()
    mock_ts.project_code = "DEFAULT"

    with patch("testgen.common.models.test_suite.TestSuite.get", return_value=mock_ts):
        from testgen.commands.run_test_execution import run_test_execution_in_background
        run_test_execution_in_background(test_suite_id)

    mock_session.add.assert_called_once()
    added = mock_session.add.call_args[0][0]
    assert added.job_key == "run-tests"
    assert added.kwargs == {"test_suite_id": str(test_suite_id)}
    assert added.source == "ui"
    assert added.project_code == "DEFAULT"
    mock_session.commit.assert_called_once()
