"""Unit tests for how write_to_app_db extracts row values for the positional COPY."""
import csv
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text

from testgen.common.database.database_service import write_to_app_db

pytestmark = pytest.mark.unit


def _mappings(query: str) -> list:
    with create_engine("sqlite://").connect() as connection:
        return list(connection.execute(text(query)).mappings())


def _written_rows(data: list, column_names: list[str]) -> list[list[str]]:
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value = cursor

    with patch(
        "testgen.common.database.database_service._init_db_connection", return_value=connection
    ):
        write_to_app_db(data, column_names, "test_results")

    buffer = cursor.copy_expert.call_args[0][1]
    buffer.seek(0)
    return list(csv.reader(buffer))


def test_row_mapping_values_follow_the_column_names_not_the_select_order():
    rows = [
        *_mappings("SELECT 'sig' AS result_signal, 1 AS result_code, 'meas' AS result_measure"),
        *_mappings("SELECT 'meas2' AS result_measure, 2 AS result_code, 'sig2' AS result_signal"),
    ]

    written = _written_rows(rows, ["result_signal", "result_code", "result_measure"])

    assert written == [["sig", "1", "meas"], ["sig2", "2", "meas2"]]


def test_plain_sequences_are_written_positionally():
    assert _written_rows([["a", "b"], ["c", "d"]], ["one", "two"]) == [["a", "b"], ["c", "d"]]


def test_nan_is_written_as_null():
    assert _written_rows([[float("nan"), 1]], ["one", "two"]) == [["", "1"]]


def test_column_names_iterable_is_consumed_once():
    written = _written_rows(_mappings("SELECT 1 AS one, 2 AS two"), iter(["one", "two"]))

    assert written == [["1", "2"]]
