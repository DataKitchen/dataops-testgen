"""
Unit tests for testgen.commands.contract_term_diff.
pytest -m unit tests/unit/commands/test_contract_term_diff.py
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Strip DB session decorator — functions run without a real connection
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_session(monkeypatch):
    monkeypatch.setattr(
        "testgen.commands.contract_term_diff.with_database_session",
        lambda f: f,
    )
    monkeypatch.setattr(
        "testgen.commands.contract_term_diff.get_tg_schema",
        lambda: "tg",
    )


# ---------------------------------------------------------------------------
# _snap_threshold_from_rule
# ---------------------------------------------------------------------------

class Test_SnapThresholdFromRule:
    def test_must_be(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({"mustBe": 0.95}) == "0.95"

    def test_must_be_greater_than(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({"mustBeGreaterThan": 100}) == "100"

    def test_must_be_greater_or_equal(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({"mustBeGreaterOrEqualTo": 0}) == "0"

    def test_must_be_less_than(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({"mustBeLessThan": 5}) == "5"

    def test_must_be_less_or_equal(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({"mustBeLessOrEqualTo": 10}) == "10"

    def test_must_be_between(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({"mustBeBetween": [0.1, 0.9]}) == "0.1,0.9"

    def test_must_be_between_wrong_length_returns_none(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({"mustBeBetween": [0.1]}) is None

    def test_no_threshold_key_returns_none(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({"id": "abc", "element": "t.c"}) is None

    def test_empty_rule_returns_none(self):
        from testgen.commands.contract_term_diff import _snap_threshold_from_rule
        assert _snap_threshold_from_rule({}) is None


# ---------------------------------------------------------------------------
# _cur_threshold_from_row
# ---------------------------------------------------------------------------

class Test_CurThresholdFromRow:
    def test_lower_and_upper_combined(self):
        from testgen.commands.contract_term_diff import _cur_threshold_from_row
        assert _cur_threshold_from_row({"lower_tolerance": 0.1, "upper_tolerance": 0.9}) == "0.1,0.9"

    def test_threshold_value_only(self):
        from testgen.commands.contract_term_diff import _cur_threshold_from_row
        assert _cur_threshold_from_row({"threshold_value": 0.95, "lower_tolerance": None, "upper_tolerance": None}) == "0.95"

    def test_all_none_returns_empty_string(self):
        from testgen.commands.contract_term_diff import _cur_threshold_from_row
        assert _cur_threshold_from_row({"threshold_value": None, "lower_tolerance": None, "upper_tolerance": None}) == ""

    def test_partial_lower_none_falls_through_to_threshold(self):
        from testgen.commands.contract_term_diff import _cur_threshold_from_row
        # Only one of lower/upper is set — pair not formed, falls through to threshold_value
        assert _cur_threshold_from_row({"lower_tolerance": None, "upper_tolerance": 0.9, "threshold_value": 5}) == "5"


# ---------------------------------------------------------------------------
# _thresholds_differ
# ---------------------------------------------------------------------------

class Test_ThresholdsDiffer:
    def test_identical_strings_not_different(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert not _thresholds_differ("0.95", "0.95")

    def test_numerically_equivalent_not_different(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert not _thresholds_differ("1.0", "1")

    def test_numeric_values_different(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert _thresholds_differ("0.95", "0.90")

    def test_between_identical_not_different(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert not _thresholds_differ("0.1,0.9", "0.1,0.9")

    def test_between_numerically_equivalent_not_different(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert not _thresholds_differ("0.10,0.90", "0.1,0.9")

    def test_between_upper_differs(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert _thresholds_differ("0.1,0.9", "0.1,0.8")

    def test_mismatched_part_count(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert _thresholds_differ("0.1,0.9", "0.5")

    def test_non_numeric_identical_not_different(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert not _thresholds_differ("abc", "abc")

    def test_non_numeric_different(self):
        from testgen.commands.contract_term_diff import _thresholds_differ
        assert _thresholds_differ("abc", "def")


# ---------------------------------------------------------------------------
# _element_str
# ---------------------------------------------------------------------------

class Test_ElementStr:
    def test_table_and_column(self):
        from testgen.commands.contract_term_diff import _element_str
        assert _element_str({"table_name": "orders", "column_name": "amount"}) == "orders.amount"

    def test_table_only_empty_column(self):
        from testgen.commands.contract_term_diff import _element_str
        assert _element_str({"table_name": "orders", "column_name": ""}) == "orders"

    def test_table_only_none_column(self):
        from testgen.commands.contract_term_diff import _element_str
        assert _element_str({"table_name": "orders", "column_name": None}) == "orders"

    def test_both_empty(self):
        from testgen.commands.contract_term_diff import _element_str
        assert _element_str({"table_name": "", "column_name": ""}) == ""


# ---------------------------------------------------------------------------
# compute_term_diff (snapshot_suite_id path — single fetch_dict_from_db call)
# ---------------------------------------------------------------------------

_YAML_ONE_RULE = """
quality:
  - id: rule-001
    element: orders.amount
    mustBe: 0.95
"""

_YAML_NO_RULES = "quality: []"

_YAML_NO_THRESHOLD = """
quality:
  - id: rule-001
    element: orders.amount
"""


def _row(id: str = "rule-001", test_type: str = "text", table: str = "orders",
         col: str = "amount", threshold: float | None = 0.95,
         last_status: str | None = "passed") -> dict:
    return {
        "id": id,
        "test_type": test_type,
        "table_name": table,
        "column_name": col,
        "threshold_value": threshold,
        "lower_tolerance": None,
        "upper_tolerance": None,
        "last_status": last_status,
    }


def _diff(saved_yaml: str, test_rows: list[dict], anomalies: list[dict] | None = None):
    """Run compute_term_diff with the snapshot_suite_id path."""
    from testgen.commands.contract_term_diff import compute_term_diff
    with patch("testgen.commands.contract_term_diff.fetch_dict_from_db", return_value=test_rows):
        return compute_term_diff(
            table_group_id="tg-1",
            saved_yaml=saved_yaml,
            anomalies=anomalies or [],
            snapshot_suite_id="suite-snap",
        )


class Test_ComputeTermDiff_Same:
    def test_status_same_when_ids_match_and_threshold_unchanged(self):
        result = _diff(_YAML_ONE_RULE, [_row(threshold=0.95)])
        assert result.entries[0].status.value == "same"

    def test_same_counts_saved_and_current(self):
        result = _diff(_YAML_ONE_RULE, [_row()])
        assert result.saved_count == 1
        assert result.current_count == 1

    def test_same_entry_carries_last_result(self):
        result = _diff(_YAML_ONE_RULE, [_row(last_status="passed")])
        assert result.entries[0].last_result == "passed"

    def test_no_threshold_in_rule_treated_as_same(self):
        result = _diff(_YAML_NO_THRESHOLD, [_row(threshold=99.0)])
        assert result.entries[0].status.value == "same"


class Test_ComputeTermDiff_Changed:
    def test_changed_when_threshold_differs(self):
        result = _diff(_YAML_ONE_RULE, [_row(threshold=0.80)])
        assert result.entries[0].status.value == "changed"

    def test_changed_detail_shows_old_and_new_threshold(self):
        result = _diff(_YAML_ONE_RULE, [_row(threshold=0.80)])
        detail = result.entries[0].detail
        assert "0.95" in detail
        assert "0.8" in detail

    def test_numerically_equivalent_threshold_not_changed(self):
        result = _diff(_YAML_ONE_RULE, [_row(threshold=0.9500)])
        assert result.entries[0].status.value == "same"


class Test_ComputeTermDiff_Deleted:
    def test_deleted_when_id_not_in_db(self):
        result = _diff(_YAML_ONE_RULE, [])
        assert result.entries[0].status.value == "deleted"

    def test_deleted_entry_element_preserved(self):
        result = _diff(_YAML_ONE_RULE, [])
        assert result.entries[0].element == "orders.amount"

    def test_deleted_entry_last_result_is_none(self):
        result = _diff(_YAML_ONE_RULE, [])
        assert result.entries[0].last_result is None


class Test_ComputeTermDiff_New:
    def test_new_when_id_in_db_not_in_snapshot(self):
        result = _diff(_YAML_NO_RULES, [_row(id="rule-999")])
        assert result.entries[0].status.value == "new"

    def test_new_entry_element_from_db_row(self):
        result = _diff(_YAML_NO_RULES, [_row(id="rule-999", table="orders", col="amount")])
        assert result.entries[0].element == "orders.amount"


class Test_ComputeTermDiff_StatusCounts:
    def test_passed_increments_test_passed(self):
        result = _diff(_YAML_ONE_RULE, [_row(last_status="passed")])
        assert result.tg_test_passed == 1

    def test_failed_increments_test_failed(self):
        result = _diff(_YAML_ONE_RULE, [_row(last_status="failed")])
        assert result.tg_test_failed == 1

    def test_warning_increments_test_warning(self):
        result = _diff(_YAML_ONE_RULE, [_row(last_status="warning")])
        assert result.tg_test_warning == 1

    def test_none_status_increments_not_run(self):
        result = _diff(_YAML_ONE_RULE, [_row(last_status=None)])
        assert result.tg_test_not_run == 1


class Test_ComputeTermDiff_Hygiene:
    def test_definite_counted_for_contract_element(self):
        anomaly = {"table_name": "orders", "column_name": "amount", "issue_likelihood": "Definite"}
        result = _diff(_YAML_ONE_RULE, [_row()], anomalies=[anomaly])
        assert result.tg_hygiene_definite == 1

    def test_likely_counted_for_contract_element(self):
        anomaly = {"table_name": "orders", "column_name": "amount", "issue_likelihood": "Likely"}
        result = _diff(_YAML_ONE_RULE, [_row()], anomalies=[anomaly])
        assert result.tg_hygiene_likely == 1

    def test_possible_counted_for_contract_element(self):
        anomaly = {"table_name": "orders", "column_name": "amount", "issue_likelihood": "Possible"}
        result = _diff(_YAML_ONE_RULE, [_row()], anomalies=[anomaly])
        assert result.tg_hygiene_possible == 1

    def test_anomaly_ignored_for_non_contract_element(self):
        anomaly = {"table_name": "other", "column_name": "col", "issue_likelihood": "Definite"}
        result = _diff(_YAML_ONE_RULE, [_row()], anomalies=[anomaly])
        assert result.tg_hygiene_definite == 0


class Test_ComputeTermDiff_EdgeCases:
    def test_invalid_yaml_returns_empty_result(self):
        result = _diff(":::invalid:::", [])
        assert result.entries == []
        assert result.saved_count == 0

    def test_empty_yaml_returns_empty_result(self):
        result = _diff(_YAML_NO_RULES, [])
        assert result.entries == []

    def test_non_dict_yaml_returns_empty_result(self):
        result = _diff("- just a list", [])
        assert result.entries == []
