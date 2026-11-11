"""Test type SQL scales by a substituted parameter without integer overflow."""

import re
from pathlib import Path

import pytest
from yaml import safe_load

import testgen

pytestmark = pytest.mark.unit

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"

# A product followed by a division by a parameter's scale: "x * {PARAM}/100.0" multiplies first, so an
# integer column times an integer parameter overflows on SQL Server before the division widens it.
_MULTIPLY_THEN_SCALE = re.compile(r"\*\s*\{[A-Z_]+\}\s*/")


def _sql() -> list[tuple[str, str]]:
    sql = []
    for path in sorted(YAML_DIR.glob("*.yaml")):
        test_type = safe_load(path.read_text())["test_types"]
        name = test_type["test_type"]
        for condition in test_type.get("cat_test_conditions") or []:
            sql.append((f"{name} {condition['sql_flavor']} measure", condition["measure"] or ""))
        for lookup in test_type.get("target_data_lookups") or []:
            sql.append((f"{name} {lookup['sql_flavor']} lookup", lookup["lookup_query"] or ""))
        for template in test_type.get("test_templates") or []:
            sql.append((f"{name} {template['sql_flavor']} template", template["template"] or ""))
    return sql


def test_a_parameter_is_scaled_before_it_multiplies():
    sql = _sql()
    assert any(name.startswith("Aggregate_Balance_Percent mssql template") for name, _ in sql)
    assert [name for name, text in sql if _MULTIPLY_THEN_SCALE.search(text)] == []
