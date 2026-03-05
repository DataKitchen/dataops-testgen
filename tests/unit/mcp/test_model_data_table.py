from unittest.mock import patch
from uuid import uuid4

from testgen.common.models.data_table import DataTable


@patch("testgen.common.models.data_table.get_current_session")
def test_select_table_names_returns_list(session_mock):
    session_mock.return_value.scalars.return_value.all.return_value = ["customers", "orders", "products"]

    result = DataTable.select_table_names(table_groups_id=uuid4())

    assert result == ["customers", "orders", "products"]
    session_mock.return_value.scalars.assert_called_once()


@patch("testgen.common.models.data_table.get_current_session")
def test_select_table_names_empty(session_mock):
    session_mock.return_value.scalars.return_value.all.return_value = []

    result = DataTable.select_table_names(table_groups_id=uuid4())

    assert result == []


@patch("testgen.common.models.data_table.get_current_session")
def test_count_tables(session_mock):
    session_mock.return_value.scalar.return_value = 42

    result = DataTable.count_tables(table_groups_id=uuid4())

    assert result == 42


@patch("testgen.common.models.data_table.get_current_session")
def test_count_tables_none_returns_zero(session_mock):
    session_mock.return_value.scalar.return_value = None

    result = DataTable.count_tables(table_groups_id=uuid4())

    assert result == 0
