"""The SQL Server measures and lookups of the test type catalogue are valid T-SQL."""

import re
from pathlib import Path

import pytest
from yaml import safe_load

import testgen

pytestmark = pytest.mark.unit

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"


def _mssql_sql() -> list[tuple[str, str]]:
    sql = []
    for path in sorted(YAML_DIR.glob("*.yaml")):
        test_type = safe_load(path.read_text())["test_types"]
        for condition in test_type.get("cat_test_conditions") or []:
            if condition["sql_flavor"] == "mssql":
                sql.append((f"{test_type['test_type']} measure", condition["measure"]))
        for lookup in test_type.get("target_data_lookups") or []:
            if lookup["sql_flavor"] == "mssql":
                sql.append((f"{test_type['test_type']} lookup", lookup["lookup_query"] or ""))
    return sql


def test_mssql_sql_concatenates_with_plus():
    sql = _mssql_sql()
    assert len(sql) > 100
    offenders = [name for name, text in sql if "||" in re.sub(r"'(?:[^']|'')*'", "''", text)]
    assert offenders == []
