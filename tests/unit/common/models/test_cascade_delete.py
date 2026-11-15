"""What the table group and test suite cascades remove besides the rows keyed by their own ids."""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

pytestmark = pytest.mark.unit


def _statements(session: MagicMock) -> tuple[list[str], dict]:
    sql, params = session.execute.call_args.args
    statements = [" ".join(part.split()) for part in str(sql).split(";") if part.strip()]
    return statements, params


def _statement_on(statements: list[str], table: str) -> list[str]:
    return [statement for statement in statements if re.match(rf"DELETE FROM {table}\b", statement)]


def test_table_group_cascade_deletes_every_job_that_names_the_table_group():
    table_group_id = uuid4()
    session = MagicMock()
    with (
        patch("testgen.common.models.table_group.get_current_session", return_value=session),
        patch.object(TestSuite, "select_minimal_where", return_value=[]),
        patch.object(TableGroup, "delete_where"),
    ):
        TableGroup.cascade_delete([table_group_id])

    statements, params = _statements(session)
    assert "DELETE FROM job_executions WHERE kwargs->>'table_group_id' IN :table_group_id_texts" in statements
    assert params["table_group_id_texts"] == (str(table_group_id),)


def test_table_group_cascade_deletes_its_schema_change_log():
    session = MagicMock()
    with (
        patch("testgen.common.models.table_group.get_current_session", return_value=session),
        patch.object(TestSuite, "select_minimal_where", return_value=[]),
        patch.object(TableGroup, "delete_where"),
    ):
        TableGroup.cascade_delete([str(uuid4())])

    statements, _ = _statements(session)
    [log_delete] = _statement_on(statements, "data_structure_log")
    assert "dsl.table_groups_id" in log_delete
    assert "IN :table_group_ids" in log_delete


def test_table_group_cascade_deletes_its_test_suites_first():
    suite_id = uuid4()
    session = MagicMock()
    with (
        patch("testgen.common.models.table_group.get_current_session", return_value=session),
        patch.object(TestSuite, "select_minimal_where", return_value=[SimpleNamespace(id=suite_id)]),
        patch.object(TestSuite, "cascade_delete") as suite_cascade,
        patch.object(TableGroup, "delete_where"),
    ):
        TableGroup.cascade_delete([str(uuid4())])

    suite_cascade.assert_called_once_with([suite_id])


def test_test_suite_cascade_deletes_every_job_that_names_the_suite_but_a_table_group_setup():
    suite_id = uuid4()
    session = MagicMock()
    with (
        patch("testgen.common.models.test_suite.get_current_session", return_value=session),
        patch.object(TestSuite, "delete_where"),
    ):
        TestSuite.cascade_delete([suite_id])

    statements, params = _statements(session)
    assert any(
        statement.endswith(
            "DELETE FROM job_executions WHERE kwargs->>'test_suite_id' IN :test_suite_id_texts"
            " OR (kwargs->>'monitor_suite_id' IN :test_suite_id_texts AND job_key <> 'refresh-data-catalog')"
        )
        for statement in statements
    )
    assert params["test_suite_id_texts"] == (str(suite_id),)
