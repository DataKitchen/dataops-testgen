"""SQL Server queries test for a blank value by length, which no collation changes."""

import re

import pytest

from tests.unit.template.mssql_sql import mssql_sql

pytestmark = pytest.mark.unit

SPACE = "__SPACE__"
# An ordering comparison with a single-space literal, which the collation decides; <> is not one
SPACE_COMPARISON = re.compile(rf"(?<!<)>=?\s*{SPACE}|<(?!>)=?\s*{SPACE}|{SPACE}\s*(?:>|<(?!>))")


def _with_space_literals_marked(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"N?' '(?!')", SPACE, sql)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def test_mssql_blank_checks_do_not_compare_with_a_space():
    offenders = [name for name, text in mssql_sql() if SPACE_COMPARISON.search(_with_space_literals_marked(text))]
    assert offenders == []


def test_the_check_finds_a_space_comparison():
    assert SPACE_COMPARISON.search(_with_space_literals_marked("WHERE val > ' '"))
    assert not SPACE_COMPARISON.search(_with_space_literals_marked("WHERE DATALENGTH(RTRIM(val)) > 0 AND x <> 'a b'"))
