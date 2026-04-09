"""
Unit tests verifying that every deletable term type is correctly removed from the
in-memory contract YAML by _delete_term_yaml_patch.

Covers all 13 deletable term types across three sources:
  - Profiling (6): Min Value, Max Value, Min Length, Max Length, Format, Logical Type
  - DDL (7): Data Type, Not Null (required + nullable), Primary Key, Foreign Key
  - Governance (3): Classification, CDE, Description

pytest -m unit tests/unit/ui/test_contract_term_deletion.py
"""
from __future__ import annotations

import copy

import pytest

pytestmark = pytest.mark.unit

from testgen.ui.views.data_contract_yaml import _delete_term_yaml_patch  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixture factory
# ---------------------------------------------------------------------------

def _doc() -> dict:
    """A minimal contract YAML doc containing every deletable term type."""
    return {
        "schema": [
            {
                "name": "orders",
                "properties": [
                    {
                        "name": "order_id",
                        # DDL terms
                        "physicalType": "bigint",
                        "required": True,
                        "nullable": False,
                        "logicalType": "integer",
                        # Governance terms
                        "classification": "internal",
                        "criticalDataElement": True,
                        "description": "Unique order identifier",
                        # Profiling + DDL constraint terms (customProperties)
                        "customProperties": [
                            {"property": "testgen.primaryKey", "value": True},
                            {"property": "testgen.minimum", "value": 1},
                            {"property": "testgen.maximum", "value": 999999},
                            {"property": "testgen.minLength", "value": 1},
                            {"property": "testgen.maxLength", "value": 20},
                            {"property": "testgen.format", "value": "numeric"},
                        ],
                    }
                ],
            }
        ],
        "quality": [],
        "references": [
            {"from": "orders.order_id", "to": "customers.id"},
        ],
    }


def _cp_keys(prop: dict) -> set[str]:
    """Return the set of customProperty keys in a property dict."""
    return {cp["property"] for cp in prop.get("customProperties", [])}


def _prop(doc: dict) -> dict:
    """Shortcut to the single property dict inside the doc."""
    return doc["schema"][0]["properties"][0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _delete(doc: dict, term_name: str, source: str) -> tuple[bool, str]:
    return _delete_term_yaml_patch(term_name, source, "orders", "order_id", "", doc)


# ---------------------------------------------------------------------------
# Profiling term deletions
# ---------------------------------------------------------------------------

class Test_ProfilingTermDeletion:
    def test_min_value_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Min Value", "profiling")
        assert patched is True, err
        assert "testgen.minimum" not in _cp_keys(_prop(doc))

    def test_max_value_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Max Value", "profiling")
        assert patched is True, err
        assert "testgen.maximum" not in _cp_keys(_prop(doc))

    def test_min_length_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Min Length", "profiling")
        assert patched is True, err
        assert "testgen.minLength" not in _cp_keys(_prop(doc))

    def test_max_length_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Max Length", "profiling")
        assert patched is True, err
        assert "testgen.maxLength" not in _cp_keys(_prop(doc))

    def test_format_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Format", "profiling")
        assert patched is True, err
        assert "testgen.format" not in _cp_keys(_prop(doc))

    def test_logical_type_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Logical Type", "profiling")
        assert patched is True, err
        assert "logicalType" not in _prop(doc)

    def test_customProperties_cleaned_up_after_all_terms_deleted(self):
        """customProperties should be removed entirely once all keys are gone."""
        doc = _doc()
        # Remove all profiling keys (leave primaryKey, which is DDL)
        for term in ("Min Value", "Max Value", "Min Length", "Max Length", "Format"):
            _delete(doc, term, "profiling")
        # primaryKey is still in customProperties
        assert "testgen.primaryKey" in _cp_keys(_prop(doc))
        # Remove the last key
        _delete(doc, "Primary Key", "ddl")
        assert "customProperties" not in _prop(doc)


# ---------------------------------------------------------------------------
# DDL term deletions
# ---------------------------------------------------------------------------

class Test_DDLTermDeletion:
    def test_data_type_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Data Type", "ddl")
        assert patched is True, err
        assert "physicalType" not in _prop(doc)

    def test_not_null_removes_required_and_nullable(self):
        doc = _doc()
        patched, err = _delete(doc, "Not Null", "ddl")
        assert patched is True, err
        prop = _prop(doc)
        assert "required" not in prop
        assert "nullable" not in prop

    def test_primary_key_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Primary Key", "ddl")
        assert patched is True, err
        assert "testgen.primaryKey" not in _cp_keys(_prop(doc))

    def test_foreign_key_is_removed_from_references(self):
        doc = _doc()
        assert len(doc["references"]) == 1
        patched, err = _delete(doc, "Foreign Key", "ddl")
        assert patched is True, err
        assert len(doc["references"]) == 0

    def test_foreign_key_matched_by_column_name_alone(self):
        """FK ref using bare column name (not table.col) should still match."""
        doc = _doc()
        doc["references"] = [{"from": "order_id", "to": "customers.id"}]
        patched, err = _delete(doc, "Foreign Key", "ddl")
        assert patched is True, err
        assert len(doc["references"]) == 0

    def test_foreign_key_matched_when_from_is_list(self):
        """FK ref where 'from' is a list of column keys should still match."""
        doc = _doc()
        doc["references"] = [{"from": ["orders.order_id", "orders.customer_id"], "to": "customers.id"}]
        patched, err = _delete(doc, "Foreign Key", "ddl")
        assert patched is True, err
        assert len(doc["references"]) == 0

    def test_other_fk_references_not_removed(self):
        """Only the matching FK reference should be removed; others stay."""
        doc = _doc()
        doc["references"] = [
            {"from": "orders.order_id", "to": "customers.id"},
            {"from": "orders.product_id", "to": "products.id"},
        ]
        _delete(doc, "Foreign Key", "ddl")
        assert len(doc["references"]) == 1
        assert doc["references"][0]["from"] == "orders.product_id"


# ---------------------------------------------------------------------------
# Governance term deletions
# ---------------------------------------------------------------------------

class Test_GovernanceTermDeletion:
    def test_classification_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Classification", "governance")
        assert patched is True, err
        assert "classification" not in _prop(doc)

    def test_cde_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "CDE", "governance")
        assert patched is True, err
        assert "criticalDataElement" not in _prop(doc)

    def test_description_is_removed(self):
        doc = _doc()
        patched, err = _delete(doc, "Description", "governance")
        assert patched is True, err
        assert "description" not in _prop(doc)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class Test_DeletionErrorCases:
    def test_returns_false_for_unknown_table(self):
        doc = _doc()
        patched, err = _delete_term_yaml_patch("Min Value", "profiling", "nonexistent", "order_id", "", doc)
        assert patched is False
        assert "nonexistent" in err

    def test_returns_false_for_unknown_column(self):
        doc = _doc()
        patched, err = _delete_term_yaml_patch("Min Value", "profiling", "orders", "nonexistent_col", "", doc)
        assert patched is False
        assert "nonexistent_col" in err

    def test_returns_false_for_missing_fk_reference(self):
        doc = _doc()
        doc["references"] = []
        patched, _err = _delete(doc, "Foreign Key", "ddl")
        assert patched is False

    def test_deleting_absent_profiling_term_still_returns_true(self):
        """Popping a missing key is a no-op but still considered patched (column found)."""
        doc = _doc()
        # Remove testgen.minimum from customProperties first
        prop = _prop(doc)
        prop["customProperties"] = [cp for cp in prop.get("customProperties", [])
                                     if cp["property"] != "testgen.minimum"]
        patched, err = _delete(doc, "Min Value", "profiling")
        assert patched is True, err

    def test_original_doc_not_mutated_on_failure(self):
        doc = _doc()
        original = copy.deepcopy(doc)
        _delete_term_yaml_patch("Min Value", "profiling", "wrong_table", "order_id", "", doc)
        assert doc == original

    def test_other_columns_not_affected_by_deletion(self):
        """Deleting a term from one column must not touch sibling columns."""
        doc = _doc()
        doc["schema"][0]["properties"].append({
            "name": "customer_id",
            "classification": "confidential",
            "logicalTypeOptions": {"minimum": 1},
        })
        _delete(doc, "Classification", "governance")
        sibling = doc["schema"][0]["properties"][1]
        assert sibling.get("classification") == "confidential"
