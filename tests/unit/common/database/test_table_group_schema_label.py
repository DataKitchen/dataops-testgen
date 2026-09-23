"""Resolving a table group's schema label from its connection."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.database.table_group_service import schema_label_for_table_group

pytestmark = pytest.mark.unit

MODULE = "testgen.common.database.table_group_service"


def _connection(sql_flavor_code):
    connection = MagicMock()
    connection.sql_flavor_code = sql_flavor_code
    return connection


@pytest.mark.parametrize(
    ("sql_flavor_code", "expected"),
    [
        ("files", None),
        ("salesforce_data360", "Data Space"),
        ("duckdb", "Schema"),
        ("postgresql", "Schema"),
    ],
)
def test_the_label_follows_the_connection_flavor_code(sql_flavor_code, expected):
    with patch(f"{MODULE}.Connection.get_by_table_group", return_value=_connection(sql_flavor_code)):
        assert schema_label_for_table_group(uuid4()) == expected


def test_a_table_group_with_no_connection_falls_back_to_schema():
    with patch(f"{MODULE}.Connection.get_by_table_group", return_value=None):
        assert schema_label_for_table_group(uuid4()) == "Schema"
