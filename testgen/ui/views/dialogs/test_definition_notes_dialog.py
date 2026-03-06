import streamlit as st

from testgen.common.models import with_database_session
from testgen.common.models.test_definition import TestDefinitionNote
from testgen.ui.components import widgets as testgen
from testgen.ui.queries import test_result_queries
from testgen.ui.session import session


@st.dialog(title="Test Notes", on_dismiss="rerun")
@with_database_session
def test_definition_notes_dialog(test_definition_id: str, test_label: dict) -> None:
    current_user = session.auth.user.username if session.auth.user else "unknown"
    notes = TestDefinitionNote.get_notes(test_definition_id)

    def on_note_added(payload: dict) -> None:
        TestDefinitionNote.add_note(test_definition_id, payload["text"], current_user)
        test_result_queries.get_test_results.clear()

    def on_note_updated(payload: dict) -> None:
        TestDefinitionNote.update_note(payload["id"], payload["text"])

    def on_note_deleted(payload: dict) -> None:
        TestDefinitionNote.delete_note(payload["id"])
        test_result_queries.get_test_results.clear()

    testgen.testgen_component(
        "test_definition_notes",
        props={
            "test_label": test_label,
            "notes": notes,
            "current_user": current_user,
        },
        on_change_handlers={
            "NoteAdded": on_note_added,
            "NoteUpdated": on_note_updated,
            "NoteDeleted": on_note_deleted,
        },
    )
