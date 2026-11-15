"""Tests for adding one note to several selected tests."""

from unittest.mock import MagicMock, patch

import pytest

from testgen.common.models.test_definition import MissingTestDefinitionError
from testgen.ui.services import test_note_service as service

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "Note added to 1 test."),
        (3, "Note added to 3 tests."),
    ],
)
def test_the_message_counts_the_tests_given_the_note(count, expected):
    ids = [f"td{index}" for index in range(count)]
    with patch.object(service.TestDefinitionNote, "add_notes", return_value=[MagicMock()] * count) as add_notes:
        assert service.add_note_to_tests(ids, "  checked  ", "alice") == expected

    add_notes.assert_called_once_with(ids, "checked", "alice")


@pytest.mark.parametrize(("ids", "text"), [(["td"], "   "), ([], "checked")])
def test_a_blank_note_or_an_empty_selection_adds_nothing(ids, text):
    with patch.object(service.TestDefinitionNote, "add_notes") as add_notes:
        assert service.add_note_to_tests(ids, text, "alice") is None

    add_notes.assert_not_called()


def test_a_selection_whose_tests_are_all_gone_is_refused():
    with (
        patch.object(service.TestDefinitionNote, "add_notes", return_value=[]),
        pytest.raises(MissingTestDefinitionError, match=service.NO_TESTS_LEFT_MESSAGE),
    ):
        service.add_note_to_tests(["deleted"], "checked", "alice")


def test_the_toast_reports_the_tests_given_the_note():
    with (
        patch.object(service, "st") as st_mock,
        patch.object(service.TestDefinitionNote, "add_notes", return_value=[MagicMock()] * 2),
    ):
        service.toast_note_added_to_tests(["a", "b"], "checked", "alice")

    st_mock.toast.assert_called_once_with("Note added to 2 tests.", icon=":material/check:")
    st_mock.cache_data.clear.assert_called_once()


def test_the_toast_reports_a_selection_whose_tests_are_all_gone():
    with (
        patch.object(service, "st") as st_mock,
        patch.object(service.TestDefinitionNote, "add_notes", return_value=[]),
    ):
        service.toast_note_added_to_tests(["deleted"], "checked", "alice")

    st_mock.toast.assert_called_once_with(service.NO_TESTS_LEFT_MESSAGE, icon=":material/error:")
    st_mock.cache_data.clear.assert_not_called()
