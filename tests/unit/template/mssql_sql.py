"""The SQL Server queries in the templates, for tests that check every one of them."""

import re
from pathlib import Path

from yaml import safe_load

import testgen

TEMPLATE_DIR = Path(testgen.__file__).parent / "template"

# Catalog queries read only system views and INFORMATION_SCHEMA, never a target table.
CATALOG_DIRS = {"data_chars"}


def mssql_sql() -> list[tuple[str, str]]:
    """Return every SQL Server test, lookup, and flavor template that reads target tables, as (name, SQL) pairs."""
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


def without_comments_and_literals(sql: str) -> str:
    """Return ``sql`` with its line comments removed and its string literals emptied."""
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)
