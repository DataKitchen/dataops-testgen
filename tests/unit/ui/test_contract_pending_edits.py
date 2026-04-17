"""
Unit tests for the pending edit accumulation and persistence model.

pytest -m unit tests/unit/ui/test_contract_pending_edits.py
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Mock Streamlit machinery before importing app code
# ---------------------------------------------------------------------------

def _mock_streamlit() -> None:
    import streamlit.components.v2 as _sv2
    _sv2.component = MagicMock(return_value=MagicMock())
    sys.modules.setdefault(
        "testgen.ui.components.widgets.testgen_component", MagicMock()
    )

_mock_streamlit()

from testgen.ui.views.data_contract_yaml import (  # noqa: E402
    _apply_pending_governance_edit,
    _apply_pending_test_edit,
    _build_pending_governance_edit,
    _gov_field_to_db_col,
    _patch_yaml_governance,
    _pending_edit_count,
)


# ---------------------------------------------------------------------------
# Test_PendingEditAccumulation
# ---------------------------------------------------------------------------

class Test_PendingEditAccumulation:
    def test_governance_edit_added_to_pending_set(self):
        pending = {}
        result = _apply_pending_governance_edit(pending, "orders", "customer_id", "Classification", "restricted")
        assert len(result["governance"]) == 1
        assert result["governance"][0]["field"] == "Classification"
        assert result["governance"][0]["value"] == "restricted"

    def test_second_edit_to_same_field_replaces_first(self):
        pending = {}
        pending = _apply_pending_governance_edit(pending, "orders", "customer_id", "Classification", "confidential")
        pending = _apply_pending_governance_edit(pending, "orders", "customer_id", "Classification", "restricted")
        gov = pending["governance"]
        assert len(gov) == 1
        assert gov[0]["value"] == "restricted"

    def test_edits_to_different_fields_accumulate_independently(self):
        pending = {}
        pending = _apply_pending_governance_edit(pending, "orders", "email", "Classification", "restricted")
        pending = _apply_pending_governance_edit(pending, "orders", "email", "Description", "Email address")
        assert len(pending["governance"]) == 2

    def test_edits_to_different_columns_accumulate_independently(self):
        pending = {}
        pending = _apply_pending_governance_edit(pending, "orders", "email", "Classification", "restricted")
        pending = _apply_pending_governance_edit(pending, "orders", "customer_id", "Classification", "confidential")
        assert len(pending["governance"]) == 2

    def test_test_threshold_edit_added_to_pending_set(self):
        pending = {}
        result = _apply_pending_test_edit(pending, "rule-uuid-001", {"threshold_value": "500"})
        assert len(result["tests"]) == 1
        assert result["tests"][0]["rule_id"] == "rule-uuid-001"
        assert result["tests"][0]["threshold_value"] == "500"

    def test_second_test_edit_replaces_first(self):
        pending = {}
        pending = _apply_pending_test_edit(pending, "rule-uuid-001", {"threshold_value": "100"})
        pending = _apply_pending_test_edit(pending, "rule-uuid-001", {"threshold_value": "200"})
        assert len(pending["tests"]) == 1
        assert pending["tests"][0]["threshold_value"] == "200"

    def test_different_rules_accumulate(self):
        pending = {}
        pending = _apply_pending_test_edit(pending, "rule-001", {"threshold_value": "100"})
        pending = _apply_pending_test_edit(pending, "rule-002", {"threshold_value": "200"})
        assert len(pending["tests"]) == 2


# ---------------------------------------------------------------------------
# Test_PendingEditCount
# ---------------------------------------------------------------------------

class Test_PendingEditCount:
    def test_zero_when_empty(self):
        assert _pending_edit_count({}) == 0

    def test_counts_governance_edits(self):
        pending = {"governance": [{"table": "t", "col": "c", "field": "f", "value": "v"}]}
        assert _pending_edit_count(pending) == 1

    def test_counts_test_edits(self):
        pending = {"tests": [{"rule_id": "x", "threshold_value": "5"}]}
        assert _pending_edit_count(pending) == 1

    def test_counts_both_categories(self):
        pending = {
            "governance": [{"table": "t", "col": "c", "field": "f", "value": "v"}],
            "tests": [{"rule_id": "x", "threshold_value": "5"}, {"rule_id": "y", "threshold_value": "10"}],
        }
        assert _pending_edit_count(pending) == 3


# ---------------------------------------------------------------------------
# Test_PatchYamlGovernance
# ---------------------------------------------------------------------------

class Test_PatchYamlGovernance:
    def _doc(self, **prop_kwargs) -> dict:
        return {
            "schema": [{
                "name": "orders",
                "properties": [{"name": "customer_id", **prop_kwargs}],
            }]
        }

    def test_sets_classification(self):
        doc = self._doc()
        patched = _patch_yaml_governance(doc, "orders", "customer_id", "Classification", "restricted")
        assert patched is True
        assert doc["schema"][0]["properties"][0]["classification"] == "restricted"

    def test_sets_description(self):
        doc = self._doc()
        patched = _patch_yaml_governance(doc, "orders", "customer_id", "Description", "The customer identifier")
        assert patched is True
        assert doc["schema"][0]["properties"][0]["description"] == "The customer identifier"

    def test_sets_cde(self):
        doc = self._doc()
        patched = _patch_yaml_governance(doc, "orders", "customer_id", "CDE", True)
        assert patched is True
        assert doc["schema"][0]["properties"][0]["criticalDataElement"] is True

    def test_removes_field_when_value_none(self):
        doc = self._doc(classification="confidential")
        patched = _patch_yaml_governance(doc, "orders", "customer_id", "Classification", None)
        assert patched is True
        assert "classification" not in doc["schema"][0]["properties"][0]

    def test_returns_false_for_unknown_table(self):
        doc = self._doc()
        result = _patch_yaml_governance(doc, "nonexistent", "customer_id", "Classification", "pii")
        assert result is False

    def test_returns_false_for_unknown_column(self):
        doc = self._doc()
        result = _patch_yaml_governance(doc, "orders", "nonexistent_col", "Classification", "pii")
        assert result is False

    def test_does_not_mutate_other_tables(self):
        doc = {
            "schema": [
                {"name": "orders", "properties": [{"name": "customer_id"}]},
                {"name": "items", "properties": [{"name": "item_id"}]},
            ]
        }
        _patch_yaml_governance(doc, "orders", "customer_id", "Classification", "restricted")
        assert "classification" not in doc["schema"][1]["properties"][0]


# ---------------------------------------------------------------------------
# Test_GovFieldHelpers
# ---------------------------------------------------------------------------

class Test_GovFieldHelpers:
    def test_classification_maps_to_pii_flag(self):
        result = _gov_field_to_db_col("Classification")
        assert result is not None
        col, _ = result
        assert col == "pii_flag"

    def test_description_maps_to_description(self):
        result = _gov_field_to_db_col("Description")
        assert result is not None
        col, _ = result
        assert col == "description"

    def test_cde_maps_to_critical_data_element(self):
        result = _gov_field_to_db_col("CDE")
        assert result is not None
        col, _ = result
        assert col == "critical_data_element"

    def test_critical_data_element_alias_maps_correctly(self):
        result = _gov_field_to_db_col("Critical Data Element")
        assert result is not None
        col, _ = result
        assert col == "critical_data_element"

    def test_pii_alias_maps_to_pii_flag(self):
        result = _gov_field_to_db_col("PII")
        assert result is not None
        col, _ = result
        assert col == "pii_flag"

    def test_unknown_field_returns_none(self):
        assert _gov_field_to_db_col("NonExistentField") is None

    def test_empty_string_returns_none(self):
        assert _gov_field_to_db_col("") is None

    def test_build_pending_governance_edit_returns_correct_dict(self):
        result = _build_pending_governance_edit("orders", "email", "Classification", "restricted")
        assert result is not None
        assert result["table"] == "orders"
        assert result["col"] == "email"
        assert result["field"] == "Classification"
        assert result["value"] == "restricted"

    def test_build_pending_governance_edit_unknown_field_returns_none(self):
        result = _build_pending_governance_edit("orders", "email", "UnknownField", "value")
        assert result is None

    def test_build_pending_governance_edit_preserves_value_type(self):
        result = _build_pending_governance_edit("orders", "is_cde", "CDE", True)
        assert result is not None
        assert result["value"] is True

    def test_build_pending_governance_edit_description(self):
        result = _build_pending_governance_edit("users", "name", "Description", "Full name of the user")
        assert result is not None
        assert result["col"] == "name"
        assert result["value"] == "Full name of the user"


# ---------------------------------------------------------------------------
# Test__PersistPendingEdits — snapshot suite sync on deletion
# ---------------------------------------------------------------------------

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SNAP_ID = "bbbbbbbb-0000-0000-0000-000000000002"
RULE_ID = "cccccccc-0000-0000-0000-000000000003"


@pytest.fixture(autouse=False)
def patch_persist_deps(monkeypatch):
    """Strip DB session decorator and schema lookup from _persist_pending_edits."""
    monkeypatch.setattr(
        "testgen.ui.queries.data_contract_queries.with_database_session",
        lambda f: f,
    )
    monkeypatch.setattr(
        "testgen.ui.queries.data_contract_queries.get_tg_schema",
        lambda: "tg",
    )


class Test_PersistPendingEdits_SnapshotSync:
    """Verify that _persist_pending_edits syncs test deletions to the snapshot suite."""

    def test_deleted_test_removed_from_source(self, patch_persist_deps):
        """A _removed=True pending edit must DELETE the test from test_definitions."""
        from unittest.mock import patch as _patch
        from testgen.ui.queries.data_contract_queries import _persist_pending_edits

        pending = {"tests": [{"rule_id": RULE_ID, "_removed": True}]}
        with _patch("testgen.ui.queries.data_contract_queries.execute_db_queries",
                    return_value=([], [])) as mock_exec, \
             _patch("testgen.ui.queries.data_contract_queries.sync_import_to_snapshot_suite"):
            _persist_pending_edits(TG_ID, pending)

        all_sqls = [call[0][0][0][0] for call in mock_exec.call_args_list]
        assert any("DELETE" in sql.upper() and "test_definitions" in sql for sql in all_sqls), (
            "Expected a DELETE from test_definitions for the removed test"
        )

    def test_deletion_synced_to_snapshot_when_snapshot_suite_id_provided(self, patch_persist_deps):
        """When snapshot_suite_id is provided, sync_import_to_snapshot_suite must be called
        with the deleted test ID so the snapshot suite stays consistent.

        Regression: previously _persist_pending_edits did not call sync, leaving the
        snapshot suite with a stale copy of the deleted test.
        """
        from unittest.mock import patch as _patch
        from testgen.ui.queries.data_contract_queries import _persist_pending_edits

        pending = {"tests": [{"rule_id": RULE_ID, "_removed": True}]}
        with _patch("testgen.ui.queries.data_contract_queries.execute_db_queries",
                    return_value=([], [])), \
             _patch("testgen.ui.queries.data_contract_queries.sync_import_to_snapshot_suite",
                    return_value=None) as mock_sync:
            _persist_pending_edits(TG_ID, pending, snapshot_suite_id=SNAP_ID)

        mock_sync.assert_called_once()
        _, _, deleted_ids = mock_sync.call_args[0][1], mock_sync.call_args[0][2], mock_sync.call_args[0][3]
        assert RULE_ID in deleted_ids, (
            f"Expected {RULE_ID} in deleted_ids passed to sync_import_to_snapshot_suite"
        )

    def test_no_snapshot_sync_when_snapshot_suite_id_is_none(self, patch_persist_deps):
        """sync_import_to_snapshot_suite must NOT be called when no snapshot_suite_id is given."""
        from unittest.mock import patch as _patch
        from testgen.ui.queries.data_contract_queries import _persist_pending_edits

        pending = {"tests": [{"rule_id": RULE_ID, "_removed": True}]}
        with _patch("testgen.ui.queries.data_contract_queries.execute_db_queries",
                    return_value=([], [])), \
             _patch("testgen.ui.queries.data_contract_queries.sync_import_to_snapshot_suite",
                    return_value=None) as mock_sync:
            _persist_pending_edits(TG_ID, pending, snapshot_suite_id=None)

        mock_sync.assert_not_called()

    def test_non_removed_tests_do_not_trigger_snapshot_sync(self, patch_persist_deps):
        """Only _removed=True edits trigger snapshot sync; plain updates do not."""
        from unittest.mock import patch as _patch
        from testgen.ui.queries.data_contract_queries import _persist_pending_edits

        pending = {"tests": [{"rule_id": RULE_ID, "threshold_value": "100"}]}
        with _patch("testgen.ui.queries.data_contract_queries.execute_db_queries",
                    return_value=([], [])), \
             _patch("testgen.ui.queries.data_contract_queries.sync_import_to_snapshot_suite",
                    return_value=None) as mock_sync:
            _persist_pending_edits(TG_ID, pending, snapshot_suite_id=SNAP_ID)

        mock_sync.assert_not_called()

    def test_empty_pending_does_not_call_sync(self, patch_persist_deps):
        """No-op when pending is empty — sync must not be called."""
        from unittest.mock import patch as _patch
        from testgen.ui.queries.data_contract_queries import _persist_pending_edits

        with _patch("testgen.ui.queries.data_contract_queries.execute_db_queries",
                    return_value=([], [])), \
             _patch("testgen.ui.queries.data_contract_queries.sync_import_to_snapshot_suite",
                    return_value=None) as mock_sync:
            _persist_pending_edits(TG_ID, {}, snapshot_suite_id=SNAP_ID)

        mock_sync.assert_not_called()
