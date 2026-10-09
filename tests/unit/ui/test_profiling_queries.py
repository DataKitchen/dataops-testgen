from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.ui.queries.profiling_queries import get_columns_by_table_group

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.queries.profiling_queries"
TABLE_GROUP_ID = str(uuid4())


def _column(table_name: str, column_name: str) -> dict:
    return {"table_group_id": TABLE_GROUP_ID, "table_name": table_name, "column_name": column_name}


def test_each_column_carries_its_active_test_count():
    columns = [_column("orders", "id"), _column("orders", "total"), _column("customers", "id")]
    counts = [
        {"table_group_id": TABLE_GROUP_ID, "table_name": "orders", "column_name": "id", "count": 3},
        {"table_group_id": TABLE_GROUP_ID, "table_name": "customers", "column_name": "id", "count": 1},
    ]
    with patch(f"{MODULE}.fetch_all_from_db", side_effect=[columns, counts]) as mock_fetch:
        result = get_columns_by_table_group(TABLE_GROUP_ID, include_active_tests=True)

    assert [column["active_test_count"] for column in result] == [3, 0, 1]
    count_query, count_params = mock_fetch.call_args_list[1].args
    assert "GROUP BY table_groups_id, table_name, column_name" in count_query
    assert count_params == {"table_group_id": TABLE_GROUP_ID}


def test_columns_without_test_counts_take_one_query():
    with patch(f"{MODULE}.fetch_all_from_db", return_value=[_column("orders", "id")]) as mock_fetch:
        result = get_columns_by_table_group(TABLE_GROUP_ID)

    assert "active_test_count" not in result[0]
    mock_fetch.assert_called_once()
