"""SQL Server queries spell each name they define the same way wherever they use it.

A case-sensitive database, such as a Fabric Warehouse on its default collation, resolves names
case-sensitively, so `WITH CTE AS (...) ... FROM cte` fails there.
"""

import re

import pytest

from tests.unit.template.test_mssql_system_views import _mssql_sql

pytestmark = pytest.mark.unit

_DEFINED = (
    re.compile(r"\bAS\s+([A-Za-z_]\w*)\b(?!\s*\()", re.IGNORECASE),  # column and table aliases
    re.compile(r"\b([A-Za-z_]\w*)\s+AS\s*\(", re.IGNORECASE),  # common table expressions
)


# CAST(x AS date) names a type, not an alias
_TYPES = {
    "bigint", "binary", "bit", "char", "date", "datetime", "datetime2", "datetimeoffset", "decimal", "float",
    "int", "money", "nchar", "numeric", "nvarchar", "real", "smallint", "time", "tinyint", "varbinary", "varchar",
}


def _names_used(sql: str) -> set[str]:
    # A function call such as COUNT(*) is not a use of an alias named count
    return set(re.findall(r"\b[A-Za-z_]\w*\b(?!\s*\()", sql))


def _code(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    sql = re.sub(r'"[^"]*"', '""', sql)
    sql = re.sub(r"\{\w+\}", "", sql)
    return re.sub(r":\w+", "", sql)


def mixed_case_names(sql: str) -> set[str]:
    code = _code(sql)
    used = _names_used(code)
    defined = {name for pattern in _DEFINED for name in pattern.findall(code) if name.lower() not in _TYPES}
    return {name for name in defined if len({word for word in used if word.lower() == name.lower()}) > 1}


def test_mssql_queries_use_each_defined_name_in_one_case():
    offenders = {name: mixed for name, text in _mssql_sql() if (mixed := mixed_case_names(text))}
    assert offenders == {}


def test_the_check_finds_a_name_used_in_another_case():
    assert mixed_case_names("WITH CTE AS (SELECT 1 AS n) SELECT n FROM cte") == {"CTE"}
    assert mixed_case_names("SELECT COUNT(*) AS count FROM t ORDER BY COUNT(*) DESC") == set()
