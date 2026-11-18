"""SQL Server queries build no rows from a VALUES list, which Azure Synapse dedicated pools reject."""

import re

import pytest

from tests.unit.template.test_mssql_system_views import _mssql_sql, _without_comments_and_literals

pytestmark = pytest.mark.unit

VALUES_ROWS = re.compile(r"\bVALUES\s*\(", re.IGNORECASE)


def test_mssql_queries_build_no_rows_from_values():
    offenders = [name for name, text in _mssql_sql() if VALUES_ROWS.search(_without_comments_and_literals(text))]
    assert offenders == []


def test_the_check_finds_a_values_list():
    assert VALUES_ROWS.search("SELECT d FROM (VALUES (0), (1)) v(d)")
    assert not VALUES_ROWS.search("SELECT 0 AS d UNION ALL SELECT 1")
