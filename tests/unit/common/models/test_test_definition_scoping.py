"""Every read of test definitions carries the version predicate.

The parametrized case is the point: a read method added later and not routed through the
scoping helper fails here rather than shipping unscoped.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.test_definition import TestDefinition

pytestmark = pytest.mark.unit

READ_METHOD_ARGS = {
    "get": (uuid4(),),
    "get_for_project": (uuid4(),),
    "select_where": (),
    "select_minimal_where": (),
    "list_for_suite": (uuid4(),),
    "select_page": (),
    "get_singleton_monitor": (uuid4(), "a_table", "Volume_Trend"),
    "list_monitor_configs_for_table": (uuid4(), "a_table"),
    "get_source_data_context": (uuid4(),),
}


def _session_mock() -> MagicMock:
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = None
    session.execute.return_value.mappings.return_value.all.return_value = []
    session.execute.return_value.scalars.return_value.first.return_value = None
    session.execute.return_value.scalar.return_value = 0
    session.execute.return_value.first.return_value = None
    return session


def _emitted_sql(session: MagicMock) -> str:
    statements = [call.args[0] for call in session.execute.call_args_list]
    assert statements, "the method issued no statement"
    return " ".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in statements
    )


@pytest.mark.parametrize("method_name", sorted(READ_METHOD_ARGS))
def test_every_read_method_scopes_to_a_version(method_name):
    session = _session_mock()

    with (
        patch("testgen.common.models.entity.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
    ):
        getattr(TestDefinition, method_name)(*READ_METHOD_ARGS[method_name])

    sql = _emitted_sql(session)

    assert "version_id" in sql, f"{method_name} does not scope to a version"
    assert "suite_versions" in sql, f"{method_name} does not resolve the version"


def test_the_scoping_predicate_resolves_rather_than_naming_the_placeholder():
    session = _session_mock()

    with (
        patch("testgen.common.models.entity.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
    ):
        TestDefinition.select_where()

    assert "00000000-0000-0000-0000-000000000000" not in _emitted_sql(session)
