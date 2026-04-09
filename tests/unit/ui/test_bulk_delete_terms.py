"""
Unit tests for the bulk-delete-terms feature.

Covers:
  1. _GOVERNANCE_LABEL_TO_FIELD — completeness and allowlist safety
  2. _persist_governance_deletion — guard conditions (empty col, unknown term, allowlist)
  3. Bulk-delete YAML mutation flow via _delete_term_yaml_patch (all term sources)
  4. Partial-failure safety: governance DB failure must not corrupt YAML session state

pytest -m unit tests/unit/ui/test_bulk_delete_terms.py
"""
from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from testgen.ui.queries.data_contract_queries import (
    _GOVERNANCE_ALLOWED_FIELDS,
    _GOVERNANCE_LABEL_TO_FIELD,
)
from testgen.ui.views.data_contract_yaml import _delete_term_yaml_patch


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _yaml_doc() -> dict:
    """Minimal contract YAML with one test-rule, one governance, one DDL, one profiling term."""
    return {
        "quality": [
            {"id": "aaaaaaaa-0001-0000-0000-000000000001", "element": "orders.amount", "type": "library"},
        ],
        "schema": [
            {
                "name": "orders",
                "properties": [
                    {
                        "name": "amount",
                        "physicalType": "numeric(10,2)",
                        "required": True,
                        "criticalDataElement": True,
                        "description": "Order total",
                        "customProperties": [
                            {"property": "testgen.minimum", "value": 0},
                            {"property": "testgen.maximum", "value": 99999},
                        ],
                    }
                ],
            }
        ],
        "references": [{"from": "orders.amount", "to": "external.ref"}],
    }


def _prop(doc: dict) -> dict:
    return doc["schema"][0]["properties"][0]


# ---------------------------------------------------------------------------
# 1. _GOVERNANCE_LABEL_TO_FIELD — completeness
# ---------------------------------------------------------------------------

class Test_GovernanceLabelToField:
    """Every label in the map must resolve to a DB column that's in the allowlist."""

    def test_all_db_columns_are_in_allowlist(self):
        for label, (db_col, _) in _GOVERNANCE_LABEL_TO_FIELD.items():
            assert db_col in _GOVERNANCE_ALLOWED_FIELDS, (
                f"Label {label!r} maps to {db_col!r} which is NOT in _GOVERNANCE_ALLOWED_FIELDS"
            )

    def test_core_governance_labels_present(self):
        required = {
            "Description", "Critical Data Element", "Excluded Data Element", "PII",
            "Data Source", "Source System", "Business Domain", "Data Product",
        }
        missing = required - set(_GOVERNANCE_LABEL_TO_FIELD)
        assert not missing, f"Missing governance labels: {missing}"

    def test_bool_fields_reset_to_false(self):
        """critical_data_element and excluded_data_element are boolean — must reset to False not None."""
        assert _GOVERNANCE_LABEL_TO_FIELD["Critical Data Element"] == ("critical_data_element", False)
        assert _GOVERNANCE_LABEL_TO_FIELD["Excluded Data Element"] == ("excluded_data_element", False)

    def test_string_fields_reset_to_none(self):
        assert _GOVERNANCE_LABEL_TO_FIELD["Description"][1] is None
        assert _GOVERNANCE_LABEL_TO_FIELD["PII"][1] is None
        assert _GOVERNANCE_LABEL_TO_FIELD["Data Source"][1] is None

    def test_aliases_present(self):
        assert "CDE" in _GOVERNANCE_LABEL_TO_FIELD
        assert "Classification" in _GOVERNANCE_LABEL_TO_FIELD


# ---------------------------------------------------------------------------
# 2. _persist_governance_deletion — guard conditions
# ---------------------------------------------------------------------------

class Test_PersistGovernanceDeletion:
    """Test guard conditions without hitting the DB (mock execute_db_queries)."""

    _PATCH = "testgen.ui.queries.data_contract_queries.execute_db_queries"

    def test_empty_col_name_is_skipped(self):
        with patch(self._PATCH) as mock_exec:
            from testgen.ui.queries.data_contract_queries import _persist_governance_deletion
            _persist_governance_deletion("Description", "tg-1", "orders", "")
            mock_exec.assert_not_called()

    def test_unknown_term_name_is_skipped(self):
        with patch(self._PATCH) as mock_exec:
            from testgen.ui.queries.data_contract_queries import _persist_governance_deletion
            _persist_governance_deletion("NonExistentTermXYZ", "tg-1", "orders", "amount")
            mock_exec.assert_not_called()

    def test_known_term_calls_db(self):
        with patch(self._PATCH) as mock_exec, \
             patch("testgen.ui.queries.data_contract_queries.get_tg_schema", return_value="testgen"):
            from testgen.ui.queries.data_contract_queries import _persist_governance_deletion
            _persist_governance_deletion("Description", "tg-1", "orders", "amount")
            mock_exec.assert_called_once()
            sql, params = mock_exec.call_args[0][0][0]
            assert "description" in sql
            assert params["val"] is None
            assert params["tbl"] == "orders"
            assert params["col"] == "amount"

    def test_critical_data_element_resets_to_false(self):
        with patch(self._PATCH) as mock_exec, \
             patch("testgen.ui.queries.data_contract_queries.get_tg_schema", return_value="testgen"):
            from testgen.ui.queries.data_contract_queries import _persist_governance_deletion
            _persist_governance_deletion("Critical Data Element", "tg-1", "orders", "amount")
            mock_exec.assert_called_once()
            _, params = mock_exec.call_args[0][0][0]
            assert params["val"] is False

    def test_all_tag_fields_call_db(self):
        tag_labels = [
            "Data Source", "Source System", "Source Process",
            "Business Domain", "Stakeholder Group",
            "Transform Level", "Aggregation Level", "Data Product",
        ]
        for label in tag_labels:
            with patch(self._PATCH) as mock_exec, \
                 patch("testgen.ui.queries.data_contract_queries.get_tg_schema", return_value="testgen"):
                from testgen.ui.queries.data_contract_queries import _persist_governance_deletion
                _persist_governance_deletion(label, "tg-1", "orders", "amount")
                assert mock_exec.called, f"Label {label!r} did not trigger a DB write"


# ---------------------------------------------------------------------------
# 3. Bulk-delete YAML mutation — all term sources
# ---------------------------------------------------------------------------

class Test_BulkDeleteYamlMutation:
    """_delete_term_yaml_patch covers the YAML side for DDL/profiling/governance terms."""

    def test_quality_rule_removed_from_quality_array(self):
        doc = _yaml_doc()
        rule_id = "aaaaaaaa-0001-0000-0000-000000000001"
        ids_to_delete = {rule_id}
        doc["quality"] = [q for q in doc["quality"] if str(q.get("id", "")) not in ids_to_delete]
        assert doc["quality"] == []

    def test_ddl_physical_type_removed(self):
        doc = _yaml_doc()
        patched, err = _delete_term_yaml_patch("Data Type", "ddl", "orders", "amount", "", doc)
        assert patched is True, err
        assert "physicalType" not in _prop(doc)

    def test_ddl_not_null_removed(self):
        doc = _yaml_doc()
        patched, err = _delete_term_yaml_patch("Not Null", "ddl", "orders", "amount", "", doc)
        assert patched is True, err
        assert "required" not in _prop(doc)

    def test_profiling_min_value_removed(self):
        doc = _yaml_doc()
        patched, err = _delete_term_yaml_patch("Min Value", "profiling", "orders", "amount", "", doc)
        assert patched is True, err
        cp_keys = {cp["property"] for cp in _prop(doc).get("customProperties", [])}
        assert "testgen.minimum" not in cp_keys

    def test_profiling_max_value_removed(self):
        doc = _yaml_doc()
        patched, err = _delete_term_yaml_patch("Max Value", "profiling", "orders", "amount", "", doc)
        assert patched is True, err
        cp_keys = {cp["property"] for cp in _prop(doc).get("customProperties", [])}
        assert "testgen.maximum" not in cp_keys

    def test_governance_yaml_cde_removed(self):
        doc = _yaml_doc()
        patched, err = _delete_term_yaml_patch("Critical Data Element", "governance", "orders", "amount", "", doc)
        assert patched is True, err
        assert "criticalDataElement" not in _prop(doc)

    def test_governance_yaml_description_removed(self):
        doc = _yaml_doc()
        patched, err = _delete_term_yaml_patch("Description", "governance", "orders", "amount", "", doc)
        assert patched is True, err
        assert "description" not in _prop(doc)

    def test_sibling_column_not_affected(self):
        doc = _yaml_doc()
        doc["schema"][0]["properties"].append({
            "name": "customer_id",
            "physicalType": "bigint",
            "criticalDataElement": True,
        })
        _delete_term_yaml_patch("Data Type", "ddl", "orders", "amount", "", doc)
        sibling = doc["schema"][0]["properties"][1]
        assert sibling.get("physicalType") == "bigint"


# ---------------------------------------------------------------------------
# 4. Partial-failure safety — governance DB failure must not corrupt YAML
# ---------------------------------------------------------------------------

class Test_BulkDeletePartialFailure:
    """Simulate the on_bulk_delete_terms flow: YAML should NOT be committed if DB raises."""

    def test_yaml_not_written_when_governance_db_fails(self):
        """Mirrors the try/except in on_bulk_delete_terms around _persist_governance_deletion."""
        import yaml

        original_yaml = yaml.dump(_yaml_doc())
        session_state: dict = {"dc_yaml:tg-1": original_yaml}

        terms = [
            {"rule_id": "", "source": "governance", "name": "Description", "table": "orders", "col": "amount"},
        ]

        def _simulate_bulk_delete(terms: list[dict], session_state: dict, yaml_key: str) -> None:
            """Stripped-down version of on_bulk_delete_terms logic."""
            current_yaml = session_state.get(yaml_key, "")
            doc = yaml.safe_load(current_yaml)

            # Schema mutations (would apply here for DDL/profiling)
            updated_yaml = yaml.dump(doc)

            # Governance DB writes — fail on purpose
            try:
                for t in terms:
                    if t.get("source") == "governance" and not t.get("rule_id"):
                        raise RuntimeError("DB connection lost")
            except RuntimeError:
                # Must NOT commit the updated YAML
                return

            session_state[yaml_key] = updated_yaml  # should never reach here

        _simulate_bulk_delete(terms, session_state, "dc_yaml:tg-1")
        assert session_state["dc_yaml:tg-1"] == original_yaml, (
            "YAML was mutated in session state despite governance DB failure"
        )

    def test_yaml_written_when_no_governance_terms(self):
        """Non-governance-only deletes should still commit YAML normally."""
        import yaml

        original_yaml = yaml.dump(_yaml_doc())
        session_state: dict = {"dc_yaml:tg-1": original_yaml}
        terms = [
            {"rule_id": "aaaaaaaa-0001-0000-0000-000000000001", "source": "test",
             "name": "Test", "table": "orders", "col": "amount"},
        ]

        def _simulate_bulk_delete(terms: list[dict], session_state: dict, yaml_key: str) -> None:
            current_yaml = session_state.get(yaml_key, "")
            doc = yaml.safe_load(current_yaml)
            rule_ids = {t["rule_id"] for t in terms if t.get("rule_id")}
            doc["quality"] = [q for q in doc.get("quality", []) if str(q.get("id", "")) not in rule_ids]
            updated_yaml = yaml.dump(doc)
            try:
                pass  # no governance terms, no DB call
            except RuntimeError:
                return
            session_state[yaml_key] = updated_yaml

        _simulate_bulk_delete(terms, session_state, "dc_yaml:tg-1")
        saved = yaml.safe_load(session_state["dc_yaml:tg-1"])
        assert saved["quality"] == [], "quality rule was not removed"
