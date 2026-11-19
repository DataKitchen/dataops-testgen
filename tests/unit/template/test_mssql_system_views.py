"""SQL Server queries over target tables read no system views, which Microsoft Fabric rejects alongside user tables."""

import re

import pytest

from tests.unit.template.mssql_sql import mssql_sql, without_comments_and_literals

pytestmark = pytest.mark.unit

SYSTEM_VIEW = re.compile(r"(?:\[sys\]|\"sys\"|\bsys)\s*\.", re.IGNORECASE)


def test_mssql_target_queries_read_no_system_views():
    sql = mssql_sql()
    assert len(sql) > 100
    offenders = [name for name, text in sql if SYSTEM_VIEW.search(without_comments_and_literals(text))]
    assert offenders == []


def test_the_check_finds_a_system_view():
    assert SYSTEM_VIEW.search(without_comments_and_literals("SELECT 1 FROM t CROSS JOIN sys.all_columns a"))
    assert SYSTEM_VIEW.search(without_comments_and_literals('SELECT 1 FROM t CROSS JOIN [sys].[objects] o, "sys".columns c'))
    assert not SYSTEM_VIEW.search(without_comments_and_literals("SELECT 'sys.x' -- sys.all_columns\nFROM t"))
