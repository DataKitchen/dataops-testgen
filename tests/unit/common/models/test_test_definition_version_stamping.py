"""Every write that creates or relocates a test definition stamps the version it lands on.

A row whose version is not the one its suite resolves to is invisible to every read, so a
creation or a move that leaves the version behind produces a row nobody can see.
"""

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models import test_definition as test_definition_module
from testgen.common.models.test_definition import TestDefinition, TestDefinitionNote
from tests.unit.sql_assertions import conjuncts, equality_conjunct, scopes_to_a_version

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _one_session_for_both_modules():
    """Point ``suite_version``'s session at whatever this module's tests patched.

    The frozen-version predicate lives on ``SuiteVersion`` so there is one copy of it, and it
    reads its own module's session while these tests patch ``test_definition``'s.
    """
    with patch(
        "testgen.common.models.suite_version.get_current_session",
        side_effect=lambda: test_definition_module.get_current_session(),
    ):
        yield



def _session_mock(resolved_version=None, persisted_version=None) -> MagicMock:
    """A session whose `scalar` resolves a version, except for the write guard's own check.

    The resolution query is a `coalesce` over the draft/frozen/placeholder branches; a query
    over `test_definitions` is the update guard reading the persisted row's own version; the
    guard's frozen check is neither, and always reports the version unfrozen here so tests can
    focus on stamping behavior.
    """
    resolved = resolved_version or uuid4()
    persisted = persisted_version or uuid4()
    session = MagicMock()

    def _scalar(statement, *args, **kwargs):
        if "coalesce" in str(statement).lower():
            return resolved
        froms = getattr(statement, "get_final_froms", list)()
        if froms and getattr(froms[0], "name", None) == "test_definitions":
            return persisted
        return None

    session.scalar.side_effect = _scalar
    return session


def _session_returning_terms(terms, notes=()) -> MagicMock:
    """A session whose term query yields `terms` and whose note query yields `notes`.

    One blanket `scalars` return value hands the note copy the test definitions back, which
    fails on the first attribute a note does not have.
    """
    session = _session_mock()

    def _scalars(statement, *args, **kwargs):
        froms = statement.get_final_froms()
        result = MagicMock()
        name = getattr(froms[0], "name", None) if froms else None
        result.all.return_value = terms if name == "test_definitions" else list(notes)
        return result

    session.scalars.side_effect = _scalars
    return session


def _emitted_sql(session: MagicMock) -> str:
    statements = [call.args[0] for call in session.execute.call_args_list]
    assert statements, "the method issued no statement"
    rendered = []
    for statement in statements:
        if hasattr(statement, "compile"):
            rendered.append(
                str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            )
        else:
            rendered.append(str(statement))
    return " ".join(rendered)


def _patched(session: MagicMock):
    return (
        patch("testgen.common.models.entity.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
    )


def test_move_restamps_the_version_from_the_target_suite():
    resolved = uuid4()
    session = _session_mock(resolved)
    target_suite = uuid4()

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        TestDefinition.move([str(uuid4())], uuid4(), target_suite, target_schema="public", qualifies_table_refs=True)

    resolution = str(
        session.scalar.call_args_list[0].args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "suite_versions" in resolution, "move does not resolve the target suite's version"
    assert str(target_suite) in resolution, "move resolves a version for the wrong suite"

    sql = _emitted_sql(session)
    assert "version_id" in sql, "move leaves the definition on the source suite's version"
    assert str(resolved) in sql, "move does not write the target suite's resolved version"


def test_copy_restamps_the_version_and_drops_the_contract_term():
    resolved = uuid4()
    session = _session_mock(resolved)

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        TestDefinition.copy([str(uuid4())], uuid4(), uuid4(), target_schema="public", qualifies_table_refs=True)

    sql = _emitted_sql(session)
    insert_columns = sql[sql.index("(") : sql.index(")")]

    assert "version_id" in insert_columns, "copy does not write the version"
    assert str(resolved) in sql, "copy does not write the target suite's resolved version"
    assert "contract_term_id" in insert_columns, "copy does not clear the contract term"


def test_copy_reads_only_the_rows_of_their_resolved_version():
    session = _session_mock()

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        TestDefinition.copy([str(uuid4())], uuid4(), uuid4(), target_schema="public", qualifies_table_refs=True)

    sql = _emitted_sql(session)
    assert "suite_versions" in sql, "copy reads definitions from every version of the source suite"


def test_saving_a_new_definition_stamps_the_resolved_version():
    resolved = uuid4()
    session = _session_mock(resolved)
    suite_id = uuid4()

    definition = TestDefinition(test_suite_id=suite_id, test_type="Volume_Trend")

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        definition.save()

    assert definition.version_id == resolved


def test_saving_a_new_definition_keeps_an_explicit_version():
    chosen = uuid4()
    session = _session_mock()

    definition = TestDefinition(test_suite_id=uuid4(), test_type="Volume_Trend", version_id=chosen)

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        definition.save()

    assert definition.version_id == chosen


def test_updating_an_existing_definition_does_not_restamp_the_version():
    session = _session_mock()

    definition = TestDefinition(test_suite_id=uuid4(), test_type="Volume_Trend")
    definition.id = uuid4()

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        definition.save()

    # The UPDATE narrows by the row's version, so version_id appears in its WHERE clause; what
    # must not happen is the SET clause restamping it, which the compiled text cannot tell apart.
    statement = session.execute.call_args.args[0]
    assert "version_id" not in {column.key for column in statement._values}
    resolutions = [call for call in session.scalar.call_args_list if "coalesce" in str(call.args[0]).lower()]
    assert resolutions == [], "updating an existing definition should not resolve a new version"


def test_move_takes_only_the_rows_of_their_resolved_version():
    session = _session_mock()

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        TestDefinition.move([str(uuid4())], uuid4(), uuid4(), target_schema="public", qualifies_table_refs=True)

    narrowing = [
        call.args[0]
        for call in session.scalars.call_args_list + session.execute.call_args_list
        if scopes_to_a_version(call.args[0])
    ]
    assert narrowing, "move relocates rows belonging to versions the suite does not resolve to"


def test_copy_to_version_gives_each_copy_a_fresh_id_and_keeps_contract_identity():
    source_id, target_id = uuid4(), uuid4()
    term = TestDefinition(
        id=uuid4(), test_suite_id=uuid4(), version_id=source_id,
        contract_term_id="clause-1", test_type="Completeness",
    )
    session = _session_returning_terms([term])
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        id_map = TestDefinition.copy_to_version(source_id, target_id)

    statement = session.scalars.call_args_list[0].args[0]
    assert any(
        equality_conjunct(t, "version_id", "test_definitions", source_id)
        for t in conjuncts(statement.whereclause)
    )

    copied = session.add.call_args.args[0]
    assert id_map == {term.id: copied.id}
    assert isinstance(copied.id, UUID)
    assert copied.id != term.id
    assert copied.contract_term_id == "clause-1"
    assert copied.version_id == target_id
    assert copied.test_type == "Completeness"


def test_copy_to_version_copies_every_term_under_the_source_version():
    source_id, target_id = uuid4(), uuid4()
    first = TestDefinition(
        id=uuid4(), test_suite_id=uuid4(), version_id=source_id,
        contract_term_id="clause-1", test_type="Completeness",
    )
    second = TestDefinition(
        id=uuid4(), test_suite_id=uuid4(), version_id=source_id,
        contract_term_id="clause-2", test_type="Uniqueness",
    )
    session = _session_returning_terms([first, second])
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        id_map = TestDefinition.copy_to_version(source_id, target_id)

    statement = session.scalars.call_args_list[0].args[0]
    assert any(
        equality_conjunct(t, "version_id", "test_definitions", source_id)
        for t in conjuncts(statement.whereclause)
    )
    assert set(id_map) == {first.id, second.id}
    copied = [call.args[0] for call in session.add.call_args_list]
    assert {c.contract_term_id for c in copied} == {"clause-1", "clause-2"}
    assert all(c.version_id == target_id for c in copied)


def test_a_frozen_only_contract_gains_a_draft_carrying_its_terms():
    suite_id = uuid4()
    frozen = MagicMock(id=uuid4())
    draft = MagicMock(id=uuid4())
    old_term_id = uuid4()
    with (
        patch.object(TestDefinition.__mro__[0], "copy_to_version",
                     return_value={old_term_id: uuid4()}) as copy,
        patch("testgen.common.models.test_definition.SuiteVersion.draft_for", return_value=None),
        patch("testgen.common.models.test_definition.SuiteVersion.open_draft",
              return_value=(draft, frozen)),
    ):
        version_id, id_map = TestDefinition.resolve_write_target(suite_id)

    assert version_id == draft.id
    assert old_term_id in id_map
    assert copy.call_args.args[0] == frozen.id


def test_an_existing_draft_receives_the_write_and_nothing_is_copied():
    draft = MagicMock(id=uuid4())
    with patch("testgen.common.models.test_definition.SuiteVersion.draft_for", return_value=draft):
        version_id, id_map = TestDefinition.resolve_write_target(uuid4())

    assert version_id == draft.id
    assert id_map == {}


def test_copy_to_version_carries_each_terms_notes_onto_its_copy():
    """A note is bound to one definition by a cascading foreign key, so a copy that left the
    notes behind would strand every annotation on the version being superseded.
    """
    source_id, target_id = uuid4(), uuid4()
    term = TestDefinition(id=uuid4(), test_suite_id=uuid4(), version_id=source_id)
    note = TestDefinitionNote(
        id=uuid4(), test_definition_id=term.id, detail="checked with the data steward",
        created_by="tester",
    )
    session = _session_returning_terms([term], notes=[note])
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        id_map = TestDefinition.copy_to_version(source_id, target_id)

    added = [call.args[0] for call in session.add.call_args_list]
    copied_notes = [obj for obj in added if isinstance(obj, TestDefinitionNote)]
    assert len(copied_notes) == 1
    assert copied_notes[0].test_definition_id == id_map[term.id]
    assert copied_notes[0].detail == "checked with the data steward"
    assert copied_notes[0].created_by == "tester"
    assert copied_notes[0] is not note


def test_copy_to_version_reads_notes_of_exactly_the_terms_it_copied():
    source_id, target_id = uuid4(), uuid4()
    term = TestDefinition(id=uuid4(), test_suite_id=uuid4(), version_id=source_id)
    session = _session_returning_terms([term])
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.copy_to_version(source_id, target_id)

    note_query = session.scalars.call_args_list[-1].args[0]
    assert note_query.get_final_froms()[0].name == "test_definition_notes"


def test_a_version_with_no_terms_issues_no_note_query():
    session = _session_returning_terms([])
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.copy_to_version(uuid4(), uuid4())

    queried = [
        call.args[0].get_final_froms()[0].name for call in session.scalars.call_args_list
    ]
    assert "test_definition_notes" not in queried
