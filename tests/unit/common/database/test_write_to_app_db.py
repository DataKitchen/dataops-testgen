"""Unit tests for the header and row values write_to_app_db hands to COPY."""
import csv
from unittest.mock import MagicMock, patch

import psycopg2.sql
import pytest
from sqlalchemy import create_engine, text

from testgen.common.database.database_service import write_to_app_db

pytestmark = pytest.mark.unit


def _mappings(query: str) -> list:
    with create_engine("sqlite://").connect() as connection:
        return list(connection.execute(text(query)).mappings())


def _identifiers(node, found: list[str] | None = None) -> list[str]:
    found = [] if found is None else found
    if isinstance(node, psycopg2.sql.Composed):
        for item in node.seq:
            _identifiers(item, found)
    elif isinstance(node, psycopg2.sql.Identifier):
        found.extend(node.strings)
    return found


def _copy_call(data: list, column_names) -> tuple[list[str], list[list[str]]]:
    """Return the COPY statement's identifiers and the CSV rows for one write."""
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value = cursor

    with patch(
        "testgen.common.database.database_service._init_db_connection", return_value=connection
    ):
        write_to_app_db(data, column_names, "test_results")

    query, buffer = cursor.copy_expert.call_args[0]
    buffer.seek(0)
    return _identifiers(query), list(csv.reader(buffer))


def test_row_mapping_values_follow_the_column_names_not_the_select_order():
    rows = [
        *_mappings("SELECT 'sig' AS result_signal, 1 AS result_code, 'meas' AS result_measure"),
        *_mappings("SELECT 'meas2' AS result_measure, 2 AS result_code, 'sig2' AS result_signal"),
    ]

    header, written = _copy_call(rows, ["result_signal", "result_code", "result_measure"])

    assert header == ["test_results", "result_signal", "result_code", "result_measure"]
    assert written == [["sig", "1", "meas"], ["sig2", "2", "meas2"]]


def test_plain_sequences_are_written_positionally():
    header, written = _copy_call([["a", "b"], ["c", "d"]], ["one", "two"])

    assert header == ["test_results", "one", "two"]
    assert written == [["a", "b"], ["c", "d"]]


def test_nan_is_written_as_null():
    _, written = _copy_call([[float("nan"), 1]], ["one", "two"])

    assert written == [["", "1"]]


def test_column_names_iterable_is_consumed_once():
    header, written = _copy_call(_mappings("SELECT 1 AS one, 2 AS two"), iter(["one", "two"]))

    assert header == ["test_results", "one", "two"]
    assert written == [["1", "2"]]


def test_a_row_missing_a_header_column_raises():
    rows = _mappings("SELECT 'sig' AS result_signal, 1 AS result_code")

    with pytest.raises(KeyError):
        _copy_call(rows, ["result_signal", "result_code", "result_measure"])
