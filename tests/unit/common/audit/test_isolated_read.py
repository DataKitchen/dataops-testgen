from unittest.mock import MagicMock, patch

import pytest

from testgen.common.audit.recorder import stored_values
from testgen.common.audit.safety import isolated_read
from testgen.common.models.test_definition import TestDefinition

pytestmark = pytest.mark.unit


def test_an_audit_read_runs_in_a_savepoint_without_flushing():
    session = MagicMock()
    with patch("testgen.common.audit.safety.get_current_session", return_value=session), isolated_read() as read:
        assert read is session

    session.connection.return_value.begin_nested.assert_called_once_with()
    session.flush.assert_not_called()
    session.begin_nested.assert_not_called()


def test_a_failed_audit_read_rolls_back_to_its_savepoint_and_returns_nothing():
    session = MagicMock()
    session.execute.side_effect = RuntimeError("statement timeout")
    savepoint = session.connection.return_value.begin_nested.return_value
    with patch("testgen.common.audit.safety.get_current_session", return_value=session):
        assert stored_values(TestDefinition, "id") == {}

    exit_args = savepoint.__exit__.call_args.args
    assert exit_args[0] is RuntimeError
