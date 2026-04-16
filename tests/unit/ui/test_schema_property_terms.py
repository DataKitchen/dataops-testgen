"""
Unit tests for schema property YAML helpers.

pytest -m unit tests/unit/ui/test_schema_property_terms.py
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _mock_streamlit() -> None:
    import streamlit.components.v2 as _sv2
    _sv2.component = MagicMock(return_value=MagicMock())
    sys.modules.setdefault(
        "testgen.ui.components.widgets.testgen_component", MagicMock()
    )

_mock_streamlit()

from testgen.ui.views.data_contract_yaml import (  # noqa: E402
    _apply_pending_schema_edit,
    _apply_pending_schema_edits,
    _find_property,
    _pending_edit_count,
)

_SAMPLE_DOC = {
    "schema": [
        {
            "name": "orders",
            "properties": [
                {"name": "amount", "physicalType": "numeric(10,2)", "required": True},
                {"name": "customer_id", "physicalType": "integer"},
            ],
        }
    ],
    "x-testgen": {
        "user_schema_fields": {
            "orders.amount": ["tags", "unique"],
        }
    },
}


class Test_FindProperty:
    def test_finds_existing_column(self):
        doc = {"schema": [{"name": "orders", "properties": [{"name": "amount", "physicalType": "numeric"}]}]}
        prop = _find_property(doc, "orders", "amount")
        assert prop is not None
        assert prop["physicalType"] == "numeric"

    def test_returns_none_for_missing_table(self):
        doc = {"schema": [{"name": "orders", "properties": [{"name": "amount"}]}]}
        assert _find_property(doc, "payments", "amount") is None

    def test_returns_none_for_missing_column(self):
        doc = {"schema": [{"name": "orders", "properties": [{"name": "amount"}]}]}
        assert _find_property(doc, "orders", "total") is None

    def test_returns_none_for_empty_doc(self):
        assert _find_property({}, "orders", "amount") is None


class Test_ApplyPendingSchemaEdit:
    def test_adds_new_entry(self):
        pending = {}
        result = _apply_pending_schema_edit(pending, "orders", "amount", "tags", ["billing"])
        assert len(result["schema"]) == 1
        assert result["schema"][0] == {"table": "orders", "col": "amount", "field": "tags", "value": ["billing"]}

    def test_replaces_existing_entry_for_same_field(self):
        pending = {}
        pending = _apply_pending_schema_edit(pending, "orders", "amount", "tags", ["billing"])
        pending = _apply_pending_schema_edit(pending, "orders", "amount", "tags", ["billing", "finance"])
        assert len(pending["schema"]) == 1
        assert pending["schema"][0]["value"] == ["billing", "finance"]

    def test_accumulates_different_fields(self):
        pending = {}
        pending = _apply_pending_schema_edit(pending, "orders", "amount", "tags", ["billing"])
        pending = _apply_pending_schema_edit(pending, "orders", "amount", "unique", False)
        assert len(pending["schema"]) == 2

    def test_value_none_signals_deletion(self):
        pending = {}
        result = _apply_pending_schema_edit(pending, "orders", "amount", "tags", None)
        assert result["schema"][0]["value"] is None


class Test_ApplyPendingSchemaEdits:
    def _fresh_doc(self) -> dict:
        import copy
        return copy.deepcopy(_SAMPLE_DOC)

    def test_set_new_field(self):
        doc = self._fresh_doc()
        _apply_pending_schema_edits(doc, [{"table": "orders", "col": "amount", "field": "title", "value": "Invoice Amount"}])
        prop = _find_property(doc, "orders", "amount")
        assert prop["title"] == "Invoice Amount"
        assert "title" in doc["x-testgen"]["user_schema_fields"]["orders.amount"]

    def test_delete_field(self):
        doc = self._fresh_doc()
        # First set the field
        _apply_pending_schema_edits(doc, [{"table": "orders", "col": "amount", "field": "tags", "value": ["billing"]}])
        # Then delete it
        _apply_pending_schema_edits(doc, [{"table": "orders", "col": "amount", "field": "tags", "value": None}])
        prop = _find_property(doc, "orders", "amount")
        assert "tags" not in prop
        col_key = "orders.amount"
        assert "tags" not in doc["x-testgen"]["user_schema_fields"].get(col_key, [])

    def test_deleting_last_field_removes_col_key(self):
        doc = {"schema": [{"name": "orders", "properties": [{"name": "amount", "tags": ["x"]}]}],
               "x-testgen": {"user_schema_fields": {"orders.amount": ["tags"]}}}
        _apply_pending_schema_edits(doc, [{"table": "orders", "col": "amount", "field": "tags", "value": None}])
        assert "orders.amount" not in doc["x-testgen"]["user_schema_fields"]

    def test_set_is_idempotent(self):
        doc = self._fresh_doc()
        entry = {"table": "orders", "col": "amount", "field": "title", "value": "Test"}
        _apply_pending_schema_edits(doc, [entry])
        _apply_pending_schema_edits(doc, [entry])
        assert doc["x-testgen"]["user_schema_fields"]["orders.amount"].count("title") == 1

    def test_creates_property_path_if_missing(self):
        doc = {"schema": [{"name": "orders", "properties": []}], "x-testgen": {}}
        _apply_pending_schema_edits(doc, [{"table": "orders", "col": "new_col", "field": "title", "value": "New"}])
        prop = _find_property(doc, "orders", "new_col")
        assert prop is not None
        assert prop["title"] == "New"

    def test_custom_field_stored_alongside_curated(self):
        doc = self._fresh_doc()
        _apply_pending_schema_edits(doc, [{"table": "orders", "col": "amount", "field": "myCustomField", "value": "foo"}])
        prop = _find_property(doc, "orders", "amount")
        assert prop["myCustomField"] == "foo"
        assert "myCustomField" in doc["x-testgen"]["user_schema_fields"]["orders.amount"]


class Test_PendingEditCount:
    def test_counts_schema_edits(self):
        pending = {
            "governance": [{"field": "Description", "value": "x", "table": "t", "col": "c"}],
            "tests":      [{"rule_id": "abc"}],
            "schema":     [{"table": "t", "col": "c", "field": "tags", "value": ["x"]}],
            "deletions":  [{"source": "ddl", "name": "Data Type", "table": "t", "col": "c"}],
        }
        assert _pending_edit_count(pending) == 4

    def test_zero_without_schema_key(self):
        assert _pending_edit_count({}) == 0


# Must import after _mock_streamlit
from testgen.ui.views.data_contract_props import _build_schema_terms  # noqa: E402


class Test_BuildSchemaTerms:
    def _doc_with_schema_fields(self, fields: list[str], prop_values: dict) -> dict:
        prop = {"name": "amount", **prop_values}
        return {
            "schema": [{"name": "orders", "properties": [prop]}],
            "x-testgen": {"user_schema_fields": {"orders.amount": fields}},
        }

    def test_returns_term_for_each_user_field(self):
        doc = self._doc_with_schema_fields(["tags", "title"], {"tags": ["billing"], "title": "Amount"})
        terms = _build_schema_terms(doc, "orders", "amount")
        assert len(terms) == 2
        names = {t["name"] for t in terms}
        assert names == {"tags", "title"}

    def test_term_has_correct_metadata(self):
        doc = self._doc_with_schema_fields(["title"], {"title": "Invoice Amount"})
        terms = _build_schema_terms(doc, "orders", "amount")
        t = terms[0]
        assert t["source"] == "schema"
        assert t["verif"] == "declared"
        assert t["kind"] == "static"
        assert t["rule_id"] == "schema|orders|amount|title"

    def test_list_value_is_comma_joined(self):
        doc = self._doc_with_schema_fields(["tags"], {"tags": ["billing", "finance"]})
        terms = _build_schema_terms(doc, "orders", "amount")
        assert terms[0]["value"] == "billing, finance"

    def test_boolean_false_renders_as_string(self):
        doc = self._doc_with_schema_fields(["unique"], {"unique": False})
        terms = _build_schema_terms(doc, "orders", "amount")
        assert terms[0]["value"] == "false"

    def test_long_value_truncated_at_30_chars(self):
        doc = self._doc_with_schema_fields(["pattern"], {"pattern": "^" + "a" * 40 + "$"})
        terms = _build_schema_terms(doc, "orders", "amount")
        assert len(terms[0]["value"]) == 30
        assert terms[0]["value"].endswith("…")

    def test_returns_empty_for_no_user_fields(self):
        doc = {"schema": [{"name": "orders", "properties": [{"name": "amount"}]}], "x-testgen": {}}
        assert _build_schema_terms(doc, "orders", "amount") == []

    def test_skips_field_with_none_value_in_yaml(self):
        doc = self._doc_with_schema_fields(["tags"], {})  # tags in tracker but not in prop
        assert _build_schema_terms(doc, "orders", "amount") == []

    def test_rule_id_uses_pipe_separator(self):
        doc = self._doc_with_schema_fields(["title"], {"title": "x"})
        t = _build_schema_terms(doc, "orders", "amount")[0]
        assert "|" in t["rule_id"]
        assert ":" not in t["rule_id"]
