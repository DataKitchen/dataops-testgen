"""Test types whose measure is an actual source-data value are withheld when source data is protected."""

from pathlib import Path

import pytest
import yaml

import testgen

pytestmark = pytest.mark.unit

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"

VALUE_MEASURES = (
    "LOV_All",
    "Recency",
    "Dec_Trunc",
    "Metric_Trend",
    "CUSTOM",
    "Match_Max_Val",
    "Match_Min_Val",
    "Match_Max_Date",
    "Match_Min_Date",
    "Match_Sum",
    "Match_Fractional_Sum",
)


@pytest.mark.parametrize("test_type", VALUE_MEASURES)
def test_a_type_that_measures_a_source_value_is_redacted(test_type):
    definition = yaml.safe_load((YAML_DIR / f"test_types_{test_type}.yaml").read_text())["test_types"]
    assert definition["ai_redact_values"] is True
