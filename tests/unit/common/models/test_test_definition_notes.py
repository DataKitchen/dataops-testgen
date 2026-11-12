"""Tests for adding notes to test definitions."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.test_definition import MissingTestDefinitionError, TestDefinitionNote

pytestmark = pytest.mark.unit


def _add_notes(storage_rows: dict, ids: list) -> tuple[list[TestDefinitionNote], MagicMock]:
    session = MagicMock()
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(TestDefinitionNote, "_storage_rows", return_value=storage_rows),
    ):
        return TestDefinitionNote.add_notes(ids, "checked with the data steward", "alice"), session


def test_each_test_gets_its_own_copy_of_the_note_on_its_storage_row():
    first, second, frozen = uuid4(), uuid4(), uuid4()

    notes, session = _add_notes({first: first, second: frozen}, [first, second])

    assert [note.test_definition_id for note in notes] == [first, frozen]
    assert {(note.detail, note.created_by) for note in notes} == {("checked with the data steward", "alice")}
    assert len({note.created_at for note in notes}) == 1
    session.add_all.assert_called_once_with(notes)
    session.flush.assert_called_once()


def test_adding_a_single_note_returns_the_persisted_note():
    td_id = uuid4()
    with patch.object(TestDefinitionNote, "add_notes", return_value=[note := MagicMock()]) as add_notes:
        assert TestDefinitionNote.add_note(td_id, "text", "alice") is note

    add_notes.assert_called_once_with([td_id], "text", "alice")


def test_adding_a_single_note_to_a_missing_test_is_refused():
    with (
        patch.object(TestDefinitionNote, "add_notes", return_value=[]),
        pytest.raises(MissingTestDefinitionError),
    ):
        TestDefinitionNote.add_note(uuid4(), "text", "alice")
