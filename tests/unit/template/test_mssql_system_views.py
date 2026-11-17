"""SQL Server queries over target tables read no system views, which Microsoft Fabric rejects alongside user tables."""

import re
from pathlib import Path

import pytest
from yaml import safe_load

import testgen

pytestmark = pytest.mark.unit

TEMPLATE_DIR = Path(testgen.__file__).parent / "template"

# Catalog queries read only system views and INFORMATION_SCHEMA, never a target table.
CATALOG_DIRS = {"data_chars"}

SYSTEM_VIEW = re.compile(r"(?:\[sys\]|\"sys\"|\bsys)\s*\.", re.IGNORECASE)


def _mssql_sql() -> list[tuple[str, str]]:
    sql = []
    for path in sorted((TEMPLATE_DIR / "dbsetup_test_types").glob("*.yaml")):
        test_type = safe_load(path.read_text())["test_types"]
        name = test_type["test_type"]
        for condition in test_type.get("cat_test_conditions") or []:
            if condition["sql_flavor"] == "mssql":
                sql.append((f"{name} measure", condition["measure"]))
        for lookup in test_type.get("target_data_lookups") or []:
            if lookup["sql_flavor"] == "mssql":
                sql.append((f"{name} lookup", lookup["lookup_query"] or ""))
        for template in test_type.get("test_templates") or []:
            if template["sql_flavor"] == "mssql":
                sql.append((f"{name} template", template["template"]))
    for path in sorted((TEMPLATE_DIR / "dbsetup_anomaly_types").glob("*.yaml")):
        anomaly_type = safe_load(path.read_text())["profile_anomaly_types"]
        for lookup in anomaly_type.get("target_data_lookups") or []:
            if lookup["sql_flavor"] == "mssql":
                sql.append((f"{anomaly_type['anomaly_type']} lookup", lookup["lookup_query"] or ""))
    for path in sorted((TEMPLATE_DIR / "flavors" / "mssql").rglob("*.sql")):
        relative = path.relative_to(TEMPLATE_DIR / "flavors" / "mssql")
        if relative.parts[0] not in CATALOG_DIRS:
            sql.append((str(relative), path.read_text()))
    return sql


def _without_comments_and_literals(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def test_mssql_target_queries_read_no_system_views():
    sql = _mssql_sql()
    assert len(sql) > 100
    offenders = [name for name, text in sql if SYSTEM_VIEW.search(_without_comments_and_literals(text))]
    assert offenders == []


def test_the_check_finds_a_system_view():
    assert SYSTEM_VIEW.search(_without_comments_and_literals("SELECT 1 FROM t CROSS JOIN sys.all_columns a"))
    assert SYSTEM_VIEW.search(_without_comments_and_literals('SELECT 1 FROM t CROSS JOIN [sys].[objects] o, "sys".columns c'))
    assert not SYSTEM_VIEW.search(_without_comments_and_literals("SELECT 'sys.x' -- sys.all_columns\nFROM t"))
