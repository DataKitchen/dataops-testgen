"""The Databricks measures and lookups of the test type catalogue quote their literals as Databricks reads them."""

from pathlib import Path

import pytest
from yaml import safe_load

import testgen

pytestmark = pytest.mark.unit

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"


def _databricks_sql(test_type: str) -> list[str]:
    definition = safe_load((YAML_DIR / f"test_types_{test_type}.yaml").read_text())["test_types"]
    measures = [row["measure"] for row in definition["cat_test_conditions"] if row["sql_flavor"] == "databricks"]
    lookups = [row["lookup_query"] for row in definition["target_data_lookups"] if row["sql_flavor"] == "databricks"]
    return measures + lookups


def test_valid_characters_escapes_quotes_with_a_backslash():
    # Databricks reads '' inside a string as two adjacent literals, not an escaped quote: '''%''' is '%'
    sql = _databricks_sql("Valid_Characters")

    assert len(sql) == 2
    for text in sql:
        assert "LIKE '\\'%\\''" in text
        assert "''" not in text.replace("'\\'%\\''", "")
