"""Every write that creates or relocates a test definition stamps the version it lands on.

A row whose version is not the one its suite resolves to is invisible to every read, so a
creation or a move that leaves the version behind produces a row nobody can see.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.test_definition import TestDefinition
from testgen.testing.sql_assertions import scopes_to_a_version

pytestmark = pytest.mark.unit


def _session_mock(resolved_version=None) -> MagicMock:
    session = MagicMock()
    session.scalar.return_value = resolved_version or uuid4()
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
        TestDefinition.move([str(uuid4())], uuid4(), target_suite)

    resolution = str(
        session.scalar.call_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "suite_versions" in resolution, "move does not resolve the target suite's version"
    assert str(target_suite) in resolution, "move resolves a version for the wrong suite"

    sql = _emitted_sql(session)
    assert "version_id" in sql, "move leaves the definition on the source suite's version"
    assert resolved in session.execute.call_args.args[1].values(), (
        "move does not bind the resolved version"
    )


def test_copy_restamps_the_version_and_drops_the_contract_term():
    resolved = uuid4()
    session = _session_mock(resolved)

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        TestDefinition.copy([str(uuid4())], uuid4(), uuid4())

    sql = _emitted_sql(session)
    insert_columns = sql[sql.index("(") : sql.index(")")]

    assert "version_id" in insert_columns, "copy does not write the version"
    assert str(resolved) in sql, "copy does not write the target suite's resolved version"
    assert "contract_term_id" in insert_columns, "copy does not clear the contract term"


def test_copy_reads_only_the_rows_of_their_resolved_version():
    session = _session_mock()

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        TestDefinition.copy([str(uuid4())], uuid4(), uuid4())

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

    assert "version_id" not in _emitted_sql(session)
    session.scalar.assert_not_called()


def test_move_takes_only_the_rows_of_their_resolved_version():
    session = _session_mock()

    entity_patch, model_patch = _patched(session)
    with entity_patch, model_patch:
        TestDefinition.move([str(uuid4())], uuid4(), uuid4())

    narrowing = [
        call.args[0]
        for call in session.scalars.call_args_list + session.execute.call_args_list
        if scopes_to_a_version(call.args[0])
    ]
    assert narrowing, "move relocates rows belonging to versions the suite does not resolve to"
