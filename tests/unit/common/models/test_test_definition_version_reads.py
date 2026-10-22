"""Reading a suite version other than the one the suite resolves to."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.test_definition import TestDefinition

pytestmark = pytest.mark.unit

READS = ["select_where", "select_minimal_where", "select_page"]


def _statement(method_name: str, **kwargs):
    session = MagicMock()
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(TestDefinition, "_paginate", return_value=([], 0)) as paginate,
    ):
        getattr(TestDefinition, method_name)(TestDefinition.table_name == "orders", **kwargs)
    statement = paginate.call_args.args[0] if paginate.called else session.execute.call_args.args[0]
    return " ".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).split()
    )


@pytest.mark.parametrize("method_name", READS)
def test_a_read_with_a_version_reads_that_version_instead_of_the_resolved_one(method_name):
    version_id = uuid4()

    sql = _statement(method_name, version_id=version_id)

    assert f"test_definitions.version_id = '{version_id}'" in sql
    assert "coalesce" not in sql.lower()
    assert "test_definitions.table_name = 'orders'" in sql


@pytest.mark.parametrize("method_name", READS)
def test_a_read_without_a_version_keeps_the_resolved_version_predicate(method_name):
    assert "coalesce" in _statement(method_name).lower()
