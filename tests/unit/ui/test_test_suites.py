"""Tests for the Test Suites dialog save path in testgen.ui.views.test_suites."""

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

import testgen
from testgen.common.models.test_suite import TestSuite
from testgen.ui.views import test_suites as view

pytestmark = pytest.mark.unit

RESULT_KEY = "ts_form_dialog:result"


@pytest.fixture
def session_state():
    state: dict = {}
    with (
        patch.object(view.st, "session_state", state),
        patch.object(view, "get_test_suite_summaries"),
    ):
        yield state


def _form(**overrides) -> dict:
    data = {
        "mode": "add",
        "test_suite": "Orders",
        "table_groups_id": str(uuid4()),
        "test_suite_description": "",
        "severity": None,
        "export_to_observability": False,
        "dq_score_exclude": False,
        "deactivate_invalid_tests": False,
        "component_key": "",
        "component_type": "dataset",
        "component_name": "",
    }
    data.update(overrides)
    return data


@pytest.mark.usefixtures("db_session_mock")
def test_add_saves_a_valid_suite(session_state):
    table_group = MagicMock(project_code="demo", connection_id=3, id=uuid4())
    with (
        patch.object(view, "get_table_group", return_value=table_group),
        patch.object(TestSuite, "save", autospec=True) as mock_save,
    ):
        view.save_test_suite_form(_form(severity="Fail"))

    saved = mock_save.call_args.args[0]
    assert (saved.test_suite, saved.project_code, saved.table_groups_id) == ("Orders", "demo", table_group.id)
    assert saved.severity == "Fail"
    assert saved.deactivate_invalid_tests is False
    assert RESULT_KEY not in session_state


@pytest.mark.usefixtures("db_session_mock")
def test_add_saves_the_deactivation_setting(session_state):
    table_group = MagicMock(project_code="demo", connection_id=3, id=uuid4())
    with (
        patch.object(view, "get_table_group", return_value=table_group),
        patch.object(TestSuite, "save", autospec=True) as mock_save,
    ):
        view.save_test_suite_form(_form(deactivate_invalid_tests=True))

    assert mock_save.call_args.args[0].deactivate_invalid_tests is True


@pytest.mark.usefixtures("db_session_mock")
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"test_suite": ""}, "Test Suite Name is required."),
        ({"component_key": "k" * 101}, "Component Key must be at most 100 characters."),
        ({"severity": "Failed"}, "Severity must be one of Fail, Warning, Log."),
    ],
)
def test_add_reports_a_validation_failure_without_saving(session_state, overrides, message):
    with (
        patch.object(view, "get_table_group") as mock_get_table_group,
        patch.object(TestSuite, "save", autospec=True) as mock_save,
    ):
        view.save_test_suite_form(_form(**overrides))

    assert session_state[RESULT_KEY] == {"success": False, "message": message}
    mock_save.assert_not_called()
    mock_get_table_group.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_edit_rejected_by_validation_leaves_the_stored_suite_untouched(session_state):
    """The dialog's session commits on return, so a rejected edit must not have been
    applied to the stored suite first."""
    stored = MagicMock(test_suite="Orders", severity="Warning", component_name="Orders")
    with patch.object(view, "get_test_suite", return_value=stored) as mock_get:
        view.save_test_suite_form(
            _form(mode="edit", test_suite_id=str(uuid4()), severity="Critical", component_name="x" * 101)
        )

    assert session_state[RESULT_KEY]["success"] is False
    mock_get.assert_not_called()
    assert stored.severity == "Warning"
    assert stored.component_name == "Orders"
    stored.save.assert_not_called()


@pytest.mark.usefixtures("db_session_mock")
def test_edit_applies_the_form_to_the_stored_suite(session_state):
    stored = MagicMock(test_suite="Orders")
    with patch.object(view, "get_test_suite", return_value=stored):
        view.save_test_suite_form(
            _form(mode="edit", test_suite_id=str(uuid4()), severity="Log", component_key="orders")
        )

    assert stored.severity == "Log"
    assert stored.component_key == "orders"
    stored.save.assert_called_once()


def test_dialog_offers_only_severities_execution_recognizes():
    """Execution reads a suite's severity as ``Fail``, ``Warning`` or ``Log``; any other stored
    value turns the suite's failures into warnings."""
    source = (Path(testgen.__file__).parent / "ui/components/frontend/js/pages/test_suites.js").read_text()
    block = source[source.index("const severityOptions = ["):]
    block = block[:block.index("];")]

    assert "value: 'Failed'" not in block
    for value in ("'Fail'", "'Warning'", "'Log'", "null"):
        assert f"value: {value}" in block
