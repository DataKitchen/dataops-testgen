"""Tests for the target-database session the UI and the common services share."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import DatabaseError

from testgen.common.database.file_declarations import FileDeclaration
from testgen.common.enums import FileFormat
from testgen.ui.services.database_service import target_db_session

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.services.database_service"


def _connection(**overrides):
    connection = MagicMock()
    connection.to_dict.return_value = {"sql_flavor": "duckdb", "sql_flavor_code": "files", **overrides}
    connection.sql_flavor = "duckdb"
    return connection


@patch(f"{MODULE}.resolve_connection_params", side_effect=lambda params: params)
@patch(f"{MODULE}.get_flavor_service")
def test_one_connection_serves_every_query(mock_get_flavor, _mock_resolve):
    flavor_service = mock_get_flavor.return_value
    flavor_service.get_pre_connection_queries.return_value = []
    flavor_service.declaration_failures.return_value = {}
    engine = flavor_service.create_engine.return_value

    with target_db_session(_connection(), None) as run:
        run("SELECT 1")
        run("SELECT 2")

    engine.connect.assert_called_once()
    engine.dispose.assert_called_once()


@patch(f"{MODULE}.resolve_connection_params", side_effect=lambda params: params)
@patch(f"{MODULE}.get_flavor_service")
def test_a_failed_query_leaves_the_session_usable(mock_get_flavor, _mock_resolve):
    """Without the rollback the next query reports the aborted transaction, not its own outcome."""
    flavor_service = mock_get_flavor.return_value
    flavor_service.get_pre_connection_queries.return_value = []
    flavor_service.declaration_failures.return_value = {}
    conn = flavor_service.create_engine.return_value.connect.return_value.__enter__.return_value
    conn.execute.side_effect = [DatabaseError("boom", None, Exception("boom")), MagicMock()]

    with target_db_session(_connection(), None) as run:
        with pytest.raises(DatabaseError):
            run("SELECT bad")
        conn.rollback.assert_called_once()
        run("SELECT good")


@patch(f"{MODULE}.resolve_connection_params", side_effect=lambda params: params)
@patch(f"{MODULE}.get_flavor_service")
def test_the_declarations_that_failed_are_available_to_the_caller(mock_get_flavor, _mock_resolve):
    flavor_service = mock_get_flavor.return_value
    flavor_service.get_pre_connection_queries.return_value = []
    flavor_service.declaration_failures.return_value = {"missing": "No files matched this path."}

    with target_db_session(_connection(), None) as run:
        assert run.declaration_failures == {"missing": "No files matched this path."}


@patch(f"{MODULE}.initialize_connection")
@patch(f"{MODULE}.resolve_connection_params", side_effect=lambda params: params)
@patch(f"{MODULE}.get_flavor_service")
def test_without_a_table_group_no_declarations_reach_the_connection(mock_get_flavor, _mock_resolve, mock_init):
    flavor_service = mock_get_flavor.return_value
    flavor_service.get_pre_connection_queries.return_value = []
    flavor_service.declaration_failures.return_value = {}

    with target_db_session(_connection(), None):
        pass

    assert mock_init.call_args.args[3] == []


@patch(f"{MODULE}.initialize_connection")
@patch(f"{MODULE}.resolve_connection_params", side_effect=lambda params: params)
@patch(f"{MODULE}.get_flavor_service")
def test_a_table_group_carries_its_declarations_to_the_connection(mock_get_flavor, _mock_resolve, mock_init):
    flavor_service = mock_get_flavor.return_value
    flavor_service.get_pre_connection_queries.return_value = []
    flavor_service.declaration_failures.return_value = {}
    table_group = MagicMock(file_declarations=[{"name": "claims", "uri": "claims.csv", "format": "csv"}])

    with target_db_session(_connection(), table_group):
        pass

    assert mock_init.call_args.args[3] == [FileDeclaration(name="claims", uri="claims.csv", format=FileFormat.CSV)]
    assert "file_declarations" not in flavor_service.create_engine.call_args.args[0]
