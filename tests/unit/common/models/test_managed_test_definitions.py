from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.test_definition import ManagedTestDefinitionError, TestDefinition

pytestmark = pytest.mark.unit

SESSION = "testgen.common.models.test_definition.get_current_session"
BASE_SESSION = "testgen.common.models.get_current_session"


def _session(*, managed_match: bool) -> MagicMock:
    session = MagicMock()
    session.scalar.return_value = managed_match
    return session


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_delete_is_refused_when_a_matched_row_is_a_managed_definition():
    session = _session(managed_match=True)
    with patch(SESSION, return_value=session), patch(BASE_SESSION, return_value=session):
        with pytest.raises(ManagedTestDefinitionError):
            TestDefinition.delete_where(TestDefinition.id.in_([uuid4()]))

    session.execute.assert_not_called()


def test_delete_proceeds_when_no_matched_row_is_a_managed_definition():
    session = _session(managed_match=False)
    session.execute.return_value.rowcount = 2
    with patch(SESSION, return_value=session), patch(BASE_SESSION, return_value=session):
        deleted = TestDefinition.delete_where(TestDefinition.id.in_([uuid4()]))

    assert deleted == 2
    session.execute.assert_called_once()


def test_the_delete_guard_checks_the_callers_rows_for_a_managed_type():
    session = _session(managed_match=False)
    with patch(SESSION, return_value=session), patch(BASE_SESSION, return_value=session):
        TestDefinition.delete_where(TestDefinition.table_name == "orders")

    guard_sql = _sql(session.scalar.call_args.args[0])
    assert "test_definitions.table_name = 'orders'" in guard_sql
    assert "test_definitions.test_type IN ('Schema_Conformance')" in guard_sql


@pytest.mark.parametrize("method", ["move", "copy"])
def test_relocating_a_managed_definition_is_refused(method):
    session = MagicMock()
    session.scalar.side_effect = [uuid4(), True]
    with (
        patch(SESSION, return_value=session),
        patch.object(TestDefinition, "assert_version_writable"),
    ):
        with pytest.raises(ManagedTestDefinitionError):
            getattr(TestDefinition, method)([str(uuid4())], uuid4(), uuid4())

    session.execute.assert_not_called()
