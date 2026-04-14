"""
Unit tests for contract staleness diff (contract_staleness.py).

pytest -m unit tests/unit/commands/test_contract_staleness.py
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml

from testgen.commands.contract_staleness import (
    StaleDiff, compute_staleness_diff,
    TermDiffEntry, TermDiffResult, compute_term_diff,
)

pytestmark = pytest.mark.unit

TABLE_GROUP_ID = str(uuid4())


# ---------------------------------------------------------------------------
# StaleDiff helpers
# ---------------------------------------------------------------------------

class Test_StaleDiff:
    def test_is_empty_when_no_changes(self):
        assert StaleDiff().is_empty

    def test_is_not_empty_with_schema_change(self):
        diff = StaleDiff(schema_changes=[{"change": "added", "table": "t", "column": "c", "detail": ""}])
        assert not diff.is_empty

    def test_summary_parts_added_column(self):
        diff = StaleDiff(schema_changes=[{"change": "added", "table": "t", "column": "c", "detail": ""}])
        parts = diff.summary_parts()
        assert any("new column" in p for p in parts)

    def test_summary_parts_removed_column(self):
        diff = StaleDiff(schema_changes=[{"change": "removed", "table": "t", "column": "c", "detail": ""}])
        parts = diff.summary_parts()
        assert any("removed" in p for p in parts)

    def test_summary_parts_changed_type(self):
        diff = StaleDiff(schema_changes=[{"change": "changed", "table": "t", "column": "c", "detail": ""}])
        parts = diff.summary_parts()
        assert any("type" in p for p in parts)

    def test_summary_parts_added_test(self):
        diff = StaleDiff(quality_changes=[{"change": "added", "element": "t.c", "test_type": "Row_Ct", "detail": "", "last_result": None}])
        parts = diff.summary_parts()
        assert any("new test" in p for p in parts)

    def test_summary_parts_removed_test(self):
        diff = StaleDiff(quality_changes=[{"change": "removed", "element": "t.c", "test_type": "", "detail": "", "last_result": None}])
        parts = diff.summary_parts()
        assert any("removed" in p for p in parts)

    def test_summary_parts_governance_changes(self):
        diff = StaleDiff(governance_changes=[{"change": "changed", "table": "t", "column": "c", "field": "description", "detail": ""}])
        parts = diff.summary_parts()
        assert any("governance" in p for p in parts)

    def test_summary_parts_suite_scope_changes(self):
        diff = StaleDiff(suite_scope_changes=[{"change": "added", "suite_name": "suite_a"}])
        parts = diff.summary_parts()
        assert any("suite" in p for p in parts)

    def test_singular_grammar(self):
        diff = StaleDiff(schema_changes=[{"change": "added", "table": "t", "column": "c", "detail": ""}])
        parts = diff.summary_parts()
        # "1 new column detected" not "1 new columns detected"
        assert any("1 new column detected" == p for p in parts)

    def test_plural_grammar(self):
        diff = StaleDiff(schema_changes=[
            {"change": "added", "table": "t", "column": "c1", "detail": ""},
            {"change": "added", "table": "t", "column": "c2", "detail": ""},
        ])
        parts = diff.summary_parts()
        assert any("2 new columns detected" == p for p in parts)


# ---------------------------------------------------------------------------
# compute_staleness_diff — schema diff
# ---------------------------------------------------------------------------

def _yaml_with_schema(*columns: dict) -> str:
    """Build a minimal YAML snapshot with the given schema columns."""
    tables: dict = {}
    for col in columns:
        tbl = col["table"]
        tables.setdefault(tbl, []).append({"name": col["column"], "physicalType": col.get("type", "varchar")})
    schema = [{"name": tbl, "properties": props} for tbl, props in tables.items()]
    return yaml.dump({"schema": schema, "quality": [], "x-testgen": {"includedSuites": []}})


def _db_row(table="orders", column="id", data_type="varchar") -> dict:
    return {"table_name": table, "column_name": column, "db_data_type": data_type, "general_type": "S"}


def _suite_row(name="suite_a") -> dict:
    return {"suite_name": name}


def _patch_db(col_rows=None, test_rows=None, gov_rows=None, suite_rows=None):
    """Return a side_effect list for fetch_dict_from_db calls in compute_staleness_diff."""
    return [
        col_rows  if col_rows  is not None else [],   # data_column_chars
        test_rows if test_rows is not None else [],   # test_definitions
        gov_rows  if gov_rows  is not None else [],   # governance query
        suite_rows if suite_rows is not None else [], # test_suites
    ]


class Test_ComputeStalenessDiff_Schema:
    def test_added_column_detected(self):
        snapshot = _yaml_with_schema({"table": "orders", "column": "id"})
        db_cols = [_db_row("orders", "id"), _db_row("orders", "amount")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db(col_rows=db_cols)):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        added = [c for c in diff.schema_changes if c["change"] == "added"]
        assert len(added) == 1
        assert added[0]["column"] == "amount"

    def test_removed_column_detected(self):
        snapshot = _yaml_with_schema(
            {"table": "orders", "column": "id"},
            {"table": "orders", "column": "old_col"},
        )
        db_cols = [_db_row("orders", "id")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db(col_rows=db_cols)):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        removed = [c for c in diff.schema_changes if c["change"] == "removed"]
        assert len(removed) == 1
        assert removed[0]["column"] == "old_col"

    def test_changed_type_detected(self):
        snapshot = _yaml_with_schema({"table": "orders", "column": "amount", "type": "integer"})
        db_cols = [_db_row("orders", "amount", data_type="bigint")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db(col_rows=db_cols)):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        changed = [c for c in diff.schema_changes if c["change"] == "changed"]
        assert len(changed) == 1

    def test_no_change_when_types_match(self):
        snapshot = _yaml_with_schema({"table": "orders", "column": "id", "type": "varchar"})
        db_cols = [_db_row("orders", "id", data_type="varchar")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db(col_rows=db_cols)):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert not diff.schema_changes

    def test_equivalent_type_aliases_not_flagged(self):
        # "character varying" and "varchar" are the same — must not produce a diff.
        snapshot = _yaml_with_schema({"table": "orders", "column": "name", "type": "character varying"})
        db_cols = [_db_row("orders", "name", data_type="varchar")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db(col_rows=db_cols)):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        changed = [c for c in diff.schema_changes if c["change"] == "changed"]
        assert changed == [], f"Expected no type change but got: {changed}"

    def test_integer_vs_int_aliases_not_flagged(self):
        snapshot = _yaml_with_schema({"table": "t", "column": "c", "type": "integer"})
        db_cols = [_db_row("t", "c", data_type="int")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db(col_rows=db_cols)):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert not [c for c in diff.schema_changes if c["change"] == "changed"]

    def test_empty_snapshot_all_columns_added(self):
        snapshot = yaml.dump({"schema": [], "quality": [], "x-testgen": {"includedSuites": []}})
        db_cols = [_db_row("orders", "id"), _db_row("orders", "amount")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db(col_rows=db_cols)):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert len([c for c in diff.schema_changes if c["change"] == "added"]) == 2

    def test_invalid_yaml_returns_empty_diff(self):
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db()):
            diff = compute_staleness_diff(TABLE_GROUP_ID, "{{not valid yaml: [}")
        assert diff.is_empty

    def test_non_mapping_yaml_returns_empty_diff(self):
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_patch_db()):
            diff = compute_staleness_diff(TABLE_GROUP_ID, "- just a list")
        assert diff.is_empty


# ---------------------------------------------------------------------------
# compute_staleness_diff — quality diff
# ---------------------------------------------------------------------------

def _yaml_with_quality(rules: list[dict]) -> str:
    return yaml.dump({"schema": [], "quality": rules, "x-testgen": {"includedSuites": []}})


def _test_row(test_id: str, test_type="Row_Ct", threshold="1000") -> dict:
    return {
        "id": test_id,
        "test_type": test_type,
        "table_name": "orders",
        "column_name": None,
        "threshold_value": threshold,
        "test_description": None,
        "last_result_status": "Passed",
    }


class Test_ComputeStalenessDiff_Quality:
    def test_added_test_detected(self):
        snapshot = _yaml_with_quality([])  # no rules in snapshot
        new_id = str(uuid4())
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_patch_db(col_rows=[], test_rows=[_test_row(new_id)])):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert any(c["change"] == "added" for c in diff.quality_changes)

    def test_removed_test_detected(self):
        old_id = str(uuid4())
        snapshot = _yaml_with_quality([{"id": old_id, "type": "library", "mustBeLessOrEqualTo": 0}])
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_patch_db(col_rows=[], test_rows=[])):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert any(c["change"] == "removed" for c in diff.quality_changes)

    def test_threshold_change_detected(self):
        test_id = str(uuid4())
        snapshot = _yaml_with_quality([{"id": test_id, "type": "library", "mustBeGreaterOrEqualTo": 500}])
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_patch_db(col_rows=[], test_rows=[_test_row(test_id, threshold="1000")])):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert any(c["change"] == "changed" for c in diff.quality_changes)

    def test_no_change_when_threshold_matches(self):
        test_id = str(uuid4())
        snapshot = _yaml_with_quality([{"id": test_id, "type": "library", "mustBeGreaterOrEqualTo": 1000}])
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_patch_db(col_rows=[], test_rows=[_test_row(test_id, threshold="1000")])):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert not diff.quality_changes


# ---------------------------------------------------------------------------
# compute_staleness_diff — suite scope diff
# ---------------------------------------------------------------------------

def _yaml_with_suites(suite_names: list[str]) -> str:
    return yaml.dump({
        "schema": [], "quality": [],
        "x-testgen": {"includedSuites": suite_names},
    })


class Test_ComputeStalenessDiff_SuiteScope:
    def test_added_suite_detected(self):
        snapshot = _yaml_with_suites(["suite_a"])
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_patch_db(suite_rows=[_suite_row("suite_a"), _suite_row("suite_b")])):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert any(c["change"] == "added" and c["suite_name"] == "suite_b" for c in diff.suite_scope_changes)

    def test_removed_suite_detected(self):
        snapshot = _yaml_with_suites(["suite_a", "suite_b"])
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_patch_db(suite_rows=[_suite_row("suite_a")])):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert any(c["change"] == "removed" and c["suite_name"] == "suite_b" for c in diff.suite_scope_changes)

    def test_no_change_when_suites_match(self):
        snapshot = _yaml_with_suites(["suite_a"])
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_patch_db(suite_rows=[_suite_row("suite_a")])):
            diff = compute_staleness_diff(TABLE_GROUP_ID, snapshot)
        assert not diff.suite_scope_changes


# ---------------------------------------------------------------------------
# compute_term_diff helpers
# ---------------------------------------------------------------------------

def _term_test_row(
    test_id: str,
    threshold: str = "100",
    is_monitor: bool = False,
    last_status: str | None = None,
    table: str = "orders",
    column: str = "amount",
    lower_tolerance: str | None = None,
    upper_tolerance: str | None = None,
) -> dict:
    return {
        "id": test_id,
        "test_type": "Row_Ct",
        "table_name": table,
        "column_name": column,
        "threshold_value": threshold,
        "lower_tolerance": lower_tolerance,
        "upper_tolerance": upper_tolerance,
        "is_monitor": is_monitor,
        "last_status": last_status,  # already normalized (passed/failed/…/not_run)
    }


def _diff_patch_db(test_rows: list | None = None) -> list:
    """Return side_effect list for the single fetch_dict_from_db call in compute_term_diff."""
    return [test_rows if test_rows is not None else []]


# ---------------------------------------------------------------------------
# compute_term_diff tests
# ---------------------------------------------------------------------------

class Test_ComputeTermDiff:
    def test_same_when_threshold_matches(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1000}])
        rows = [_term_test_row(test_id, threshold="1000")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        same = [e for e in result.entries if e.status == "same"]
        assert len(same) == 1
        assert same[0].test_type == "Row_Ct"
        assert same[0].detail is None

    def test_changed_when_threshold_differs(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 500}])
        rows = [_term_test_row(test_id, threshold="1000")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        changed = [e for e in result.entries if e.status == "changed"]
        assert len(changed) == 1
        assert "500" in changed[0].detail
        assert "1000" in changed[0].detail

    def test_deleted_when_not_in_testgen(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeLessOrEqualTo": 0}])
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db([])):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        deleted = [e for e in result.entries if e.status == "deleted"]
        assert len(deleted) == 1
        assert deleted[0].element == "orders.amount"

    def test_new_when_not_in_saved_yaml(self):
        new_id = str(uuid4())
        saved = _yaml_with_quality([])
        rows = [_term_test_row(new_id, threshold="100")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        new = [e for e in result.entries if e.status == "new"]
        assert len(new) == 1

    def test_saved_and_current_counts(self):
        id1, id2 = str(uuid4()), str(uuid4())
        saved = _yaml_with_quality([{"id": id1, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 100}])
        rows = [
            _term_test_row(id1, threshold="100"),
            _term_test_row(id2, threshold="200"),
        ]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.saved_count == 1
        assert result.current_count == 2

    def test_monitor_status_counted_separately(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", is_monitor=True, last_status="passed")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.tg_monitor_passed == 1
        assert result.tg_test_passed == 0

    def test_test_status_counted_separately(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", is_monitor=False, last_status="failed")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.tg_test_failed == 1
        assert result.tg_monitor_failed == 0

    def test_not_run_when_no_result(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", last_status=None)]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.tg_test_not_run == 1

    def test_hygiene_scoped_to_contract_elements(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", table="orders", column="amount")]
        anomalies = [
            {"table_name": "orders", "column_name": "amount", "issue_likelihood": "Definite"},
            {"table_name": "users",  "column_name": "email",  "issue_likelihood": "Likely"},   # out of contract
        ]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, anomalies)
        assert result.tg_hygiene_definite == 1
        assert result.tg_hygiene_likely == 0   # excluded because not in contract elements

    def test_invalid_yaml_returns_empty_result(self):
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db([])):
            result = compute_term_diff(TABLE_GROUP_ID, "{{invalid yaml: [}", [])
        assert result.entries == []
        assert result.saved_count == 0

    def test_entry_carries_is_monitor_flag(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", is_monitor=True, last_status="passed")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.entries[0].is_monitor is True

    def test_range_same_when_bounds_match(self):
        """mustBeBetween in YAML matches lower_tolerance + upper_tolerance in DB → same."""
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeBetween": [10, 90]}])
        rows = [_term_test_row(test_id, threshold="0", lower_tolerance="10", upper_tolerance="90")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.entries[0].status == "same"

    def test_range_changed_when_bounds_differ(self):
        """mustBeBetween in YAML differs from lower_tolerance + upper_tolerance in DB → changed."""
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeBetween": [10, 90]}])
        rows = [_term_test_row(test_id, threshold="0", lower_tolerance="10", upper_tolerance="95")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.entries[0].status == "changed"
        assert "10,90" in result.entries[0].detail
        assert "10,95" in result.entries[0].detail

    def test_range_same_with_float_db_values(self):
        """DB returns lower/upper as floats (10.0, 90.0); YAML has ints (10, 90) → same."""
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeBetween": [10, 90]}])
        rows = [_term_test_row(test_id, threshold="0", lower_tolerance="10.0", upper_tolerance="90.0")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.entries[0].status == "same"
