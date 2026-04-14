"""
Unit tests for compute_staleness_diff snapshot_suite_id parameter.
pytest -m unit tests/unit/commands/test_staleness_diff_snapshot.py
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SNAP_ID = "bbbbbbbb-0000-0000-0000-000000000002"

_MINIMAL_YAML = yaml.dump({
    "apiVersion": "v3.1.0",
    "kind": "DataContract",
    "schema": [{"name": "orders", "properties": [{"name": "id", "physicalType": "int"}]}],
    "quality": [{"id": "rule-1", "element": "orders.id", "mustBe": 100}],
    "x-testgen": {"includedSuites": ["suite_a"]},
})


@pytest.fixture(autouse=True)
def patch_session(monkeypatch):
    monkeypatch.setattr(
        "testgen.commands.contract_staleness.with_database_session",
        lambda f: f,
    )
    monkeypatch.setattr(
        "testgen.commands.contract_staleness.get_tg_schema",
        lambda: "tg",
    )


def _make_fetch_side_effect(
    col_rows=None,
    test_rows=None,
    gov_rows=None,
    suite_rows=None,
    with_snapshot: bool = False,
):
    """Build a side_effect list for all fetch_dict_from_db calls in compute_staleness_diff.

    When snapshot_suite_id is set, the quality diff block is skipped, so the
    test_rows query is NOT issued. The order is: col_rows, gov_rows, suite_rows.
    When snapshot_suite_id is NOT set: col_rows, test_rows, gov_rows, suite_rows.
    """
    if with_snapshot:
        return [
            col_rows   if col_rows   is not None else [],
            gov_rows   if gov_rows   is not None else [],
            suite_rows if suite_rows is not None else [],
        ]
    return [
        col_rows   if col_rows   is not None else [],
        test_rows  if test_rows  is not None else [],
        gov_rows   if gov_rows   is not None else [],
        suite_rows if suite_rows is not None else [],
    ]


class Test_StalenessWithSnapshot:

    def test_quality_changes_suppressed_when_snapshot_suite_id_set(self):
        """quality_changes must be [] when snapshot_suite_id is non-null."""
        from testgen.commands.contract_staleness import compute_staleness_diff

        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect(
                       col_rows=[{"table_name": "orders", "column_name": "id",
                                  "general_type": "N", "data_type": "int"}],
                       gov_rows=[],
                       suite_rows=[],
                       with_snapshot=True,
                   )):
            diff = compute_staleness_diff(TG_ID, _MINIMAL_YAML, snapshot_suite_id=SNAP_ID)

        assert diff.quality_changes == []

    def test_quality_changes_computed_when_no_snapshot(self):
        """quality_changes must be computed normally when snapshot_suite_id=None."""
        from testgen.commands.contract_staleness import compute_staleness_diff

        # DB returns a different test (not matching the YAML rule-id) → added change
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect(
                       col_rows=[{"table_name": "orders", "column_name": "id",
                                  "general_type": "N", "data_type": "int"}],
                       test_rows=[{"id": "different-rule", "test_type": "Score_Test",
                                   "table_name": "orders", "column_name": "id",
                                   "threshold_value": 50, "lower_tolerance": None,
                                   "upper_tolerance": None, "test_description": None,
                                   "last_result_status": None}],
                       gov_rows=[],
                       suite_rows=[],
                   )):
            diff = compute_staleness_diff(TG_ID, _MINIMAL_YAML, snapshot_suite_id=None)

        # "different-rule" not in YAML → "added"; "rule-1" not in DB → "removed"
        assert len(diff.quality_changes) >= 1

    def test_schema_changes_still_computed_with_snapshot(self):
        """schema_changes must still be computed even when snapshot_suite_id is set."""
        from testgen.commands.contract_staleness import compute_staleness_diff

        # DB returns a NEW column not in the YAML snapshot → added schema change
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect(
                       col_rows=[
                           {"table_name": "orders", "column_name": "id",
                            "general_type": "N", "data_type": "int"},
                           {"table_name": "orders", "column_name": "new_col",
                            "general_type": "T", "data_type": "varchar"},
                       ],
                       gov_rows=[],
                       suite_rows=[],
                       with_snapshot=True,
                   )):
            diff = compute_staleness_diff(TG_ID, _MINIMAL_YAML, snapshot_suite_id=SNAP_ID)

        assert any(c["change"] == "added" for c in diff.schema_changes)

    def test_suite_scope_changes_still_computed_with_snapshot(self):
        """suite_scope_changes must still be computed even when snapshot_suite_id is set."""
        from testgen.commands.contract_staleness import compute_staleness_diff

        # DB returns a new suite not in the YAML → added suite scope change
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect(
                       col_rows=[],
                       gov_rows=[],
                       suite_rows=[{"suite_name": "suite_a"}, {"suite_name": "suite_b"}],
                       with_snapshot=True,
                   )):
            diff = compute_staleness_diff(TG_ID, _MINIMAL_YAML, snapshot_suite_id=SNAP_ID)

        assert any(c["change"] == "added" and c["suite_name"] == "suite_b"
                   for c in diff.suite_scope_changes)

    def test_suite_scope_query_excludes_snapshot_suites(self):
        """Suite scope query must contain is_contract_snapshot IS NOT TRUE."""
        from testgen.commands.contract_staleness import compute_staleness_diff

        captured_sqls: list[str] = []

        def _capture(sql, params=None, **_):
            captured_sqls.append(sql)
            # schema diff queries
            if "data_column_chars" in sql:
                return []
            # test definitions query
            if "test_definitions" in sql:
                return []
            # governance
            if "pii_flag" in sql:
                return []
            # suite scope
            if "test_suites" in sql:
                return []
            return []

        with patch("testgen.commands.contract_staleness.fetch_dict_from_db", side_effect=_capture):
            compute_staleness_diff(TG_ID, _MINIMAL_YAML)

        suite_sqls = [s for s in captured_sqls if "test_suites" in s]
        assert suite_sqls, "Expected at least one query against test_suites"
        assert any("is_contract_snapshot" in s for s in suite_sqls)
