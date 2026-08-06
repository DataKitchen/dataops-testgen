from pathlib import Path

import pytest
from yaml import safe_load

import testgen
from testgen.common.models.test_definition import (
    NON_PUBLIC_TEST_TYPES,
    TestCriteria,
    derive_test_criteria,
)

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"

# Authoritative test-type -> Criteria mapping. The derivation is pure Python (no column),
# shared by the UI lookup and MCP. This dict pins the expected facet value for every test type;
# redline here and the derivation together.
EXPECTED_CRITERIA = {
    # Custom Criteria: user authors the test in SQL (custom scope)
    "CUSTOM": TestCriteria.CUSTOM_CRITERIA,
    "Condition_Flag": TestCriteria.CUSTOM_CRITERIA,
    # Reference Dataset: compared against another dataset (referential scope)
    "Aggregate_Balance": TestCriteria.REFERENCE_DATASET,
    "Aggregate_Balance_Percent": TestCriteria.REFERENCE_DATASET,
    "Aggregate_Balance_Range": TestCriteria.REFERENCE_DATASET,
    "Aggregate_Minimum": TestCriteria.REFERENCE_DATASET,
    "Combo_Match": TestCriteria.REFERENCE_DATASET,
    "Distribution_Shift": TestCriteria.REFERENCE_DATASET,
    "Timeframe_Combo_Gain": TestCriteria.REFERENCE_DATASET,
    "Timeframe_Combo_Match": TestCriteria.REFERENCE_DATASET,
    # List of Values: tested against a set/lookup of allowed values (Set / lookup algorithm)
    "LOV_All": TestCriteria.LIST_OF_VALUES,
    "LOV_Match": TestCriteria.LIST_OF_VALUES,
    "US_State": TestCriteria.LIST_OF_VALUES,
    # Defined Rule: predefined validity/integrity rule, no user-supplied value (enumerated)
    "Dupe_Rows": TestCriteria.DEFINED_RULE,
    "Unique": TestCriteria.DEFINED_RULE,
    "Email_Format": TestCriteria.DEFINED_RULE,
    "Street_Addr_Pattern": TestCriteria.DEFINED_RULE,
    "Valid_Characters": TestCriteria.DEFINED_RULE,
    "Valid_Month": TestCriteria.DEFINED_RULE,
    "Valid_US_Zip": TestCriteria.DEFINED_RULE,
    "Valid_US_Zip3": TestCriteria.DEFINED_RULE,
    # Defined Value: user asserts the expected value/pattern (enumerated)
    "Constant": TestCriteria.DEFINED_VALUE,
    "Pattern_Match": TestCriteria.DEFINED_VALUE,
    "Required": TestCriteria.DEFINED_VALUE,
    # Defined Threshold: user tunes a numeric threshold/tolerance (fallthrough)
    "Alpha_Trunc": TestCriteria.DEFINED_THRESHOLD,
    "Avg_Shift": TestCriteria.DEFINED_THRESHOLD,
    "Daily_Record_Ct": TestCriteria.DEFINED_THRESHOLD,
    "Dec_Trunc": TestCriteria.DEFINED_THRESHOLD,
    "Distinct_Date_Ct": TestCriteria.DEFINED_THRESHOLD,
    "Distinct_Value_Ct": TestCriteria.DEFINED_THRESHOLD,
    "Freshness_Trend": TestCriteria.DEFINED_THRESHOLD,
    "Future_Date": TestCriteria.DEFINED_THRESHOLD,
    "Future_Date_1Y": TestCriteria.DEFINED_THRESHOLD,
    "Incr_Avg_Shift": TestCriteria.DEFINED_THRESHOLD,
    "Metric_Trend": TestCriteria.DEFINED_THRESHOLD,
    "Min_Date": TestCriteria.DEFINED_THRESHOLD,
    "Min_Val": TestCriteria.DEFINED_THRESHOLD,
    "Missing_Pct": TestCriteria.DEFINED_THRESHOLD,
    "Monthly_Rec_Ct": TestCriteria.DEFINED_THRESHOLD,
    "Outlier_Pct_Above": TestCriteria.DEFINED_THRESHOLD,
    "Outlier_Pct_Below": TestCriteria.DEFINED_THRESHOLD,
    "Recency": TestCriteria.DEFINED_THRESHOLD,
    "Row_Ct": TestCriteria.DEFINED_THRESHOLD,
    "Row_Ct_Pct": TestCriteria.DEFINED_THRESHOLD,
    "Table_Freshness": TestCriteria.DEFINED_THRESHOLD,
    "Unique_Pct": TestCriteria.DEFINED_THRESHOLD,
    "Variability_Increase": TestCriteria.DEFINED_THRESHOLD,
    "Variability_Decrease": TestCriteria.DEFINED_THRESHOLD,
    "Volume_Trend": TestCriteria.DEFINED_THRESHOLD,
    "Weekly_Rec_Ct": TestCriteria.DEFINED_THRESHOLD,
}


def _test_type_docs():
    for path in sorted([*YAML_DIR.glob("*.yaml"), *YAML_DIR.glob("*.yml")]):
        yield safe_load(path.read_text())["test_types"]


@pytest.mark.unit
def test_every_test_type_has_expected_criteria():
    seen = set()
    for tt in _test_type_docs():
        test_type = tt["test_type"]
        if test_type in NON_PUBLIC_TEST_TYPES:
            continue
        seen.add(test_type)
        criteria = derive_test_criteria(test_type, tt.get("test_scope"), tt.get("algorithm"))
        assert criteria == EXPECTED_CRITERIA[test_type], (
            f"{test_type}: derived {criteria!r}, expected {EXPECTED_CRITERIA[test_type]!r}"
        )
    missing = set(EXPECTED_CRITERIA) - seen
    assert not missing, f"expected-criteria mapping references unknown test types: {sorted(missing)}"


@pytest.mark.unit
def test_derive_returns_a_valid_criteria_for_every_test_type():
    for tt in _test_type_docs():
        if tt["test_type"] in NON_PUBLIC_TEST_TYPES:
            continue
        criteria = derive_test_criteria(tt["test_type"], tt.get("test_scope"), tt.get("algorithm"))
        assert isinstance(criteria, TestCriteria)
