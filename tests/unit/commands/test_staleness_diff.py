"""
Unit tests for staleness diff computation.
pytest -m unit tests/unit/commands/test_staleness_diff.py
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
TEST_ID_1 = "bbbbbbbb-0000-0000-0000-000000000001"
TEST_ID_2 = "bbbbbbbb-0000-0000-0000-000000000002"


# ---------------------------------------------------------------------------
# Strip decorators
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helper: build a minimal ODCS YAML string
# ---------------------------------------------------------------------------

def _make_saved_yaml(
    tables: list | None = None,
    quality: list | None = None,
    included_suites: list | None = None,
) -> str:
    doc: dict = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": "test-id",
        "schema": tables or [],
        "quality": quality or [],
        "x-testgen": {"includedSuites": included_suites or []},
    }
    return yaml.dump(doc)


def _make_table_schema(table: str, columns: list[dict]) -> dict:
    """Build a schema table entry for _make_saved_yaml ``tables`` arg."""
    return {
        "name": table,
        "properties": [
            {"name": col["name"], "physicalType": col.get("physicalType", "varchar")}
            for col in columns
        ],
    }


def _make_quality_rule(test_id: str, threshold: str = "100") -> dict:
    """Build a minimal ODCS quality rule with an id and mustBeGreaterOrEqualTo threshold."""
    return {
        "id": test_id,
        "type": "custom",
        "element": "orders",
        "mustBeGreaterOrEqualTo": threshold,
    }


# ---------------------------------------------------------------------------
# No-op side_effect: 4 empty DB result lists (schema, quality, governance, suites)
# ---------------------------------------------------------------------------

_EMPTY_4 = [[], [], [], []]


# ---------------------------------------------------------------------------
# Test_StaleDiffIsEmpty
# ---------------------------------------------------------------------------

class Test_StaleDiffIsEmpty:
    def test_empty_when_no_changes(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff()
        assert diff.is_empty is True

    def test_not_empty_when_schema_changes(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff(
            schema_changes=[{"change": "added", "table": "t", "column": "c", "detail": ""}]
        )
        assert diff.is_empty is False

    def test_not_empty_when_quality_changes(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff(
            quality_changes=[{"change": "added", "element": "t", "test_type": "Row_Ct",
                              "detail": "", "last_result": None}]
        )
        assert diff.is_empty is False


# ---------------------------------------------------------------------------
# Test_StaleDiffSummaryParts — pure in-memory, no DB
# ---------------------------------------------------------------------------

class Test_StaleDiffSummaryParts:
    def _schema_change(self, change: str) -> dict:
        return {"change": change, "table": "orders", "column": "id", "detail": ""}

    def _quality_change(self, change: str) -> dict:
        return {"change": change, "element": "orders", "test_type": "Row_Ct",
                "detail": "", "last_result": None}

    def test_added_columns_summary(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff(schema_changes=[self._schema_change("added"), self._schema_change("added")])
        parts = diff.summary_parts()
        assert any("2 new columns detected" in p for p in parts)

    def test_single_added_column_no_plural(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff(schema_changes=[self._schema_change("added")])
        parts = diff.summary_parts()
        assert any("1 new column detected" in p for p in parts)

    def test_added_test_summary(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff(quality_changes=[self._quality_change("added")])
        parts = diff.summary_parts()
        assert any("1 new test added" in p for p in parts)

    def test_removed_test_summary(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff(quality_changes=[self._quality_change("removed")])
        parts = diff.summary_parts()
        assert any("1 test removed" in p for p in parts)

    def test_empty_summary_when_no_changes(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff()
        assert diff.summary_parts() == []

    def test_multiple_categories_all_listed(self):
        from testgen.commands.contract_staleness import StaleDiff

        diff = StaleDiff(
            schema_changes=[self._schema_change("added")],
            quality_changes=[self._quality_change("changed")],
        )
        parts = diff.summary_parts()
        # One part for column add, one for test threshold change
        assert len(parts) >= 2
        schema_part = any("column" in p for p in parts)
        quality_part = any("test" in p for p in parts)
        assert schema_part
        assert quality_part


# ---------------------------------------------------------------------------
# Test_SchemaDiff
# ---------------------------------------------------------------------------

class Test_SchemaDiff:
    """compute_staleness_diff — schema section diffs."""

    def _run(self, saved_yaml: str, schema_rows: list, quality_rows: list | None = None,
             governance_rows: list | None = None, suite_rows: list | None = None):
        from testgen.commands.contract_staleness import compute_staleness_diff

        side_effect = [
            schema_rows,
            quality_rows or [],
            governance_rows or [],
            suite_rows or [],
        ]
        with patch(
            "testgen.commands.contract_staleness.fetch_dict_from_db",
            side_effect=side_effect,
        ):
            return compute_staleness_diff(TG_ID, saved_yaml)

    def test_new_column_detected(self):
        """DB has an extra column not in the snapshot → schema_change "added"."""
        saved = _make_saved_yaml(
            tables=[_make_table_schema("orders", [{"name": "id", "physicalType": "INTEGER"}])]
        )
        db_rows = [
            {"table_name": "orders", "column_name": "id",    "data_type": "INTEGER"},
            {"table_name": "orders", "column_name": "email", "data_type": "VARCHAR"},
        ]
        diff = self._run(saved, db_rows)
        added = [c for c in diff.schema_changes if c["change"] == "added"]
        assert len(added) == 1
        assert added[0]["column"] == "email"

    def test_removed_column_detected(self):
        """Snapshot has a column that's no longer in the DB → schema_change "removed"."""
        saved = _make_saved_yaml(
            tables=[_make_table_schema("orders", [
                {"name": "id",    "physicalType": "INTEGER"},
                {"name": "email", "physicalType": "VARCHAR"},
            ])]
        )
        db_rows = [
            {"table_name": "orders", "column_name": "id", "data_type": "INTEGER"},
        ]
        diff = self._run(saved, db_rows)
        removed = [c for c in diff.schema_changes if c["change"] == "removed"]
        assert len(removed) == 1
        assert removed[0]["column"] == "email"

    def test_type_change_detected(self):
        """Same column with a different data_type → schema_change "changed"."""
        saved = _make_saved_yaml(
            tables=[_make_table_schema("orders", [{"name": "id", "physicalType": "INTEGER"}])]
        )
        db_rows = [
            {"table_name": "orders", "column_name": "id", "data_type": "BIGINT"},
        ]
        diff = self._run(saved, db_rows)
        changed = [c for c in diff.schema_changes if c["change"] == "changed"]
        assert len(changed) == 1

    def test_no_changes_when_identical(self):
        """Snapshot and DB are identical → schema_changes is empty."""
        saved = _make_saved_yaml(
            tables=[_make_table_schema("orders", [{"name": "id", "physicalType": "INTEGER"}])]
        )
        db_rows = [
            {"table_name": "orders", "column_name": "id", "data_type": "INTEGER"},
        ]
        diff = self._run(saved, db_rows)
        assert diff.schema_changes == []


# ---------------------------------------------------------------------------
# Test_TestDiff
# ---------------------------------------------------------------------------

class Test_TestDiff:
    """compute_staleness_diff — quality (test definitions) section diffs."""

    def _run(self, saved_yaml: str, quality_rows: list, schema_rows: list | None = None,
             governance_rows: list | None = None, suite_rows: list | None = None):
        from testgen.commands.contract_staleness import compute_staleness_diff

        side_effect = [
            schema_rows or [],
            quality_rows,
            governance_rows or [],
            suite_rows or [],
        ]
        with patch(
            "testgen.commands.contract_staleness.fetch_dict_from_db",
            side_effect=side_effect,
        ):
            return compute_staleness_diff(TG_ID, saved_yaml)

    def test_new_test_detected(self):
        """Snapshot has 0 rules, DB has 1 active test → quality_changes has 1 "added"."""
        saved = _make_saved_yaml(quality=[])
        db_test = {
            "id": TEST_ID_1,
            "test_type": "Row_Ct",
            "table_name": "orders",
            "column_name": None,
            "threshold_value": "1000",
            "test_description": None,
            "last_result_status": None,
        }
        diff = self._run(saved, [db_test])
        added = [c for c in diff.quality_changes if c["change"] == "added"]
        assert len(added) == 1

    def test_removed_test_detected(self):
        """Snapshot has 1 rule with id, DB returns 0 active tests → quality_changes has 1 "removed"."""
        saved = _make_saved_yaml(quality=[_make_quality_rule(TEST_ID_1, "100")])
        diff = self._run(saved, quality_rows=[])
        removed = [c for c in diff.quality_changes if c["change"] == "removed"]
        assert len(removed) == 1

    def test_threshold_change_detected(self):
        """Snapshot rule threshold "100", DB threshold "200" → quality_changes has 1 "changed"."""
        saved = _make_saved_yaml(quality=[_make_quality_rule(TEST_ID_1, "100")])
        db_test = {
            "id": TEST_ID_1,
            "test_type": "Row_Ct",
            "table_name": "orders",
            "column_name": None,
            "threshold_value": "200",
            "test_description": None,
            "last_result_status": None,
        }
        diff = self._run(saved, [db_test])
        changed = [c for c in diff.quality_changes if c["change"] == "changed"]
        assert len(changed) == 1

    def test_no_changes_when_identical(self):
        """Snapshot rule id matches DB test with same threshold → quality_changes empty."""
        saved = _make_saved_yaml(quality=[_make_quality_rule(TEST_ID_1, "100")])
        db_test = {
            "id": TEST_ID_1,
            "test_type": "Row_Ct",
            "table_name": "orders",
            "column_name": None,
            "threshold_value": "100",
            "test_description": None,
            "last_result_status": None,
        }
        diff = self._run(saved, [db_test])
        assert diff.quality_changes == []


# ---------------------------------------------------------------------------
# Test_SuiteScopeDiff
# ---------------------------------------------------------------------------

class Test_SuiteScopeDiff:
    """compute_staleness_diff — x-testgen.includedSuites diff."""

    def _run(self, saved_yaml: str, suite_rows: list):
        from testgen.commands.contract_staleness import compute_staleness_diff

        side_effect = [
            [],          # schema cols
            [],          # quality tests
            [],          # governance
            suite_rows,  # suites
        ]
        with patch(
            "testgen.commands.contract_staleness.fetch_dict_from_db",
            side_effect=side_effect,
        ):
            return compute_staleness_diff(TG_ID, saved_yaml)

    def test_suite_added_detected(self):
        """Snapshot includedSuites=[], DB returns suite → suite_scope_changes has 1 "added"."""
        saved = _make_saved_yaml(included_suites=[])
        diff = self._run(saved, [{"suite_name": "orders_suite"}])
        added = [c for c in diff.suite_scope_changes if c["change"] == "added"]
        assert len(added) == 1
        assert added[0]["suite_name"] == "orders_suite"

    def test_suite_removed_detected(self):
        """Snapshot includedSuites=["orders_suite"], DB returns [] → suite_scope_changes has 1 "removed"."""
        saved = _make_saved_yaml(included_suites=["orders_suite"])
        diff = self._run(saved, [])
        removed = [c for c in diff.suite_scope_changes if c["change"] == "removed"]
        assert len(removed) == 1
        assert removed[0]["suite_name"] == "orders_suite"

    def test_no_scope_changes(self):
        """Snapshot and DB match exactly → suite_scope_changes empty."""
        saved = _make_saved_yaml(included_suites=["orders_suite"])
        diff = self._run(saved, [{"suite_name": "orders_suite"}])
        assert diff.suite_scope_changes == []
