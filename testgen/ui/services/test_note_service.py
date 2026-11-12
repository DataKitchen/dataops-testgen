import streamlit as st

from testgen.common.models.test_definition import MissingTestDefinitionError, TestDefinitionNote

NO_TESTS_LEFT_MESSAGE = "The selected tests no longer exist."


def add_note_to_tests(test_definition_ids: list[str], text: str, username: str) -> str | None:
    """Add one copy of a note to each given test definition that exists.

    Returns the success message, or None when the note is blank or no test is given. Raises
    ``MissingTestDefinitionError`` when none of the given test definitions exist.
    """
    detail = text.strip()
    if not detail or not test_definition_ids:
        return None
    if not (count := len(TestDefinitionNote.add_notes(test_definition_ids, detail, username))):
        raise MissingTestDefinitionError(NO_TESTS_LEFT_MESSAGE)
    return f"Note added to {count} test{'' if count == 1 else 's'}."


def toast_note_added_to_tests(test_definition_ids: list[str], text: str, username: str) -> None:
    """Add one copy of a note to each given test definition and toast the outcome."""
    try:
        message = add_note_to_tests(test_definition_ids, text, username)
    except MissingTestDefinitionError as error:
        st.toast(str(error), icon=":material/error:")
        return
    if message:
        st.toast(message, icon=":material/check:")
        st.cache_data.clear()
