"""The frequency analysis query's distinct-value hash and frequent-value ranking, run on DuckDB."""

import hashlib

import duckdb
import pytest

from testgen.common.database.database_service import process_conditionals, replace_params
from testgen.common.read_file import read_template_sql_file
from testgen.common.table_filters import table_filter_params

pytestmark = pytest.mark.unit

# Case variants, an accent, an empty string, whitespace-only and leading-space values, nulls, and tied counts
VALUES = ["b", "B", "a", "A", "é", "e", "", " ", "  x", "Z", "z", "a", "a", "B", "B", "z", "Z", None, None]


def _run(values: list[str | None], table_filter: str | None = None) -> list[dict]:
    sql = read_template_sql_file("frequency_analysis.sql", "flavors/duckdb/profiling")
    sql = replace_params(
        process_conditionals(sql, {"do_sample_bool": False}),
        {"DATA_SCHEMA": "main", "DATA_TABLE": "t", "COL_NAME": "col", **table_filter_params(table_filter, "t", "main", '"')},
    )
    con = duckdb.connect()
    con.execute("CREATE TABLE t (col VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [(value,) for value in values])
    cursor = con.execute(sql)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def test_distinct_value_hash_is_md5_of_distinct_non_null_values_in_byte_order():
    distinct = sorted({value for value in VALUES if value is not None}, key=lambda value: value.encode("utf-8"))
    expected = hashlib.md5("|".join(distinct).encode("utf-8"), usedforsecurity=False).hexdigest()

    assert {row["distinct_value_hash"] for row in _run(VALUES)} == {expected}


def test_frequent_values_break_count_ties_in_byte_order_and_skip_blanks():
    counts: dict[str, int] = {}
    for value in VALUES:
        if value is not None and value > " ":
            counts[value] = counts.get(value, 0) + 1
    expected = sorted(counts.items(), key=lambda item: (-item[1], item[0].encode("utf-8")))[:10]

    assert [(row["value"], row["value_ct"]) for row in _run(VALUES) if row["value"] is not None] == expected


def test_a_table_filter_analyzes_only_the_matching_records():
    kept = [value for value in VALUES if value is None or value.lower() == value]

    assert _run(VALUES, table_filter="col IS NULL OR col = LOWER(col)") == _run(kept)
