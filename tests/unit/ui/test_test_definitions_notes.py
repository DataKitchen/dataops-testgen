"""On the test-definitions page, writing a note takes the disposition permission, and a note for every
matching test reaches the tests the page's filters and version select."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from testgen.common.enums import SuiteType
from testgen.ui.views import test_definitions as view
from testgen.ui.views.test_definitions import TestDefinitionsPage

pytestmark = pytest.mark.unit


def _render(*, can_note: bool = True, **params) -> dict:
    """Render the page with its collaborators stubbed and return the widget's keyword arguments."""
    page = TestDefinitionsPage.__new__(TestDefinitionsPage)
    page.router = MagicMock()
    suite = MagicMock(suite_type=SuiteType.STANDARD)
    columns = pd.DataFrame({"table_name": [], "column_name": [], "test_type": [], "test_name_short": []})
    with (
        patch.object(view, "st") as st_mock,
        patch.object(view, "session") as session_mock,
        patch.object(view, "testgen") as testgen_mock,
        patch.object(view, "with_database_session", lambda func: func),
        patch.object(view, "get_test_suite", return_value=suite),
        patch.object(view, "get_table_group_minimal"),
        patch.object(view, "get_test_definitions", return_value=(pd.DataFrame({"id": []}), 0)),
        patch.object(view, "get_managed_count", return_value=0),
        patch.object(view, "run_test_type_lookup_query", return_value=pd.DataFrame()),
        patch.object(view, "get_columns", return_value=[]),
        patch.object(view, "get_test_suite_columns", return_value=columns),
        patch.object(view, "get_connection", return_value=None),
        patch.object(view, "dataframe_to_json_records", return_value=[]),
    ):
        st_mock.session_state = {}
        session_mock.auth.user_has_permission.side_effect = (
            lambda permission, *_: permission != "disposition" or can_note
        )
        page.render(test_suite_id="s1", **params)
    return testgen_mock.test_definitions_widget.call_args.kwargs


@pytest.mark.parametrize(
    ("handler", "payload"),
    [
        ("on_NoteAdded_change", {"test_definition_id": "td", "text": "checked"}),
        ("on_NoteAddedToSelected_change", {"ids": ["td"], "text": "checked"}),
        ("on_NoteUpdated_change", {"id": "n1", "test_definition_id": "td", "text": "checked"}),
        ("on_NoteDeleted_change", {"id": "n1", "test_definition_id": "td"}),
    ],
)
def test_a_user_who_cannot_disposition_writes_no_notes(handler, payload):
    handlers = _render(can_note=False)
    with (
        patch.object(view.TestDefinitionNote, "add_note") as add_note,
        patch.object(view.TestDefinitionNote, "update_note") as update_note,
        patch.object(view.TestDefinitionNote, "delete_note") as delete_note,
        patch.object(view, "toast_note_added_to_tests") as add_to_selected,
    ):
        handlers[handler](payload)

    for write in (add_note, update_note, delete_note, add_to_selected):
        write.assert_not_called()


def test_the_page_tells_the_widget_who_can_write_notes():
    assert _render(can_note=False)["data"]["permissions"]["can_note"] is False
    assert _render(can_note=True)["data"]["permissions"]["can_note"] is True


def test_adding_a_note_to_selected_tests_adds_it_to_those_tests():
    handlers = _render()
    with patch.object(view, "session"), patch.object(view, "toast_note_added_to_tests") as add:
        handlers["on_NoteAddedToSelected_change"]({"ids": ["a", "b"], "text": "checked"})

    assert add.call_args.args[:2] == (["a", "b"], "checked")


def test_adding_a_note_to_every_matching_test_adds_it_to_the_tests_the_filters_select():
    handlers = _render(table_name="orders", flagged="Flagged")
    with (
        patch.object(view, "session"),
        patch.object(view, "get_test_definition_ids", return_value=["td"]) as lookup,
        patch.object(view, "toast_note_added_to_tests") as add,
    ):
        handlers["on_NoteAddedToSelected_change"]({"ids": "all", "text": "checked"})

    assert lookup.call_args.args[1] == "orders"
    assert lookup.call_args.kwargs == {"flagged_filter": "Flagged", "version_id": None}
    assert add.call_args.args[:2] == (["td"], "checked")
