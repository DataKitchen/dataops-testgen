# Schema Property Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users add, edit, and delete ODCS v3.1.0 property-level fields (tags, title, unique, pattern, etc.) from the data contract UI, stored in the YAML via `x-testgen.user_schema_fields` with the same pending-edits staging pattern as governance edits.

**Architecture:** YAML-only storage (no DB columns). A tracker section `x-testgen.user_schema_fields` records which fields were user-added vs. auto-derived. Schema terms appear as teal chips in `static_terms`, a new SchemaButton stacks below Governance/Add-test in the column header, and a "Schema" filter pill filters by `source === 'schema'`. Edits are staged in `dc_pending["schema"]` and applied to the in-memory YAML on Save — same lifecycle as governance edits.

**Tech Stack:** Python 3.12, Streamlit dialogs (`@st.dialog`), VanJS (data_contract.js), YAML (`pyyaml`), pytest unit + AppTest functional tests.

---

## File Map

| File | Action | What changes |
|---|---|---|
| `testgen/ui/views/data_contract_yaml.py` | Modify | Add `_find_property`, `_apply_pending_schema_edit`, `_apply_pending_schema_edits`; update `_pending_edit_count` |
| `testgen/ui/views/data_contract_props.py` | Modify | Add `_build_schema_terms`; update `_extract_column_terms` call site to append schema terms; update `static_terms` serialization to include `rule_id`; add `schema` to `_SOURCE_META` |
| `testgen/ui/views/dialogs/data_contract_dialogs.py` | Modify | Add `_schema_edit_dialog` |
| `testgen/ui/views/data_contract.py` | Modify | Add `on_schema_edit` handler; update `on_bulk_delete_terms` for schema rule_ids; update pending injection for schema ghost chips; add `pending_edit_schema_keys` prop; register `SchemaEditClicked` |
| `testgen/ui/components/frontend/js/pages/data_contract.js` | Modify | `SOURCE_CLASS`/`SOURCE_LABEL` schema entries; CSS for `.term-chip.sch` and `.chip-sch`; `SchemaButton`; `ColumnRow` update; Schema filter pill; `termFilter` update; `TermsHelpPanel` SourceRow |
| `tests/unit/ui/test_schema_property_terms.py` | Create | Unit tests for YAML helpers and term builder |
| `tests/functional/ui/apps/data_contract_schema_terms.py` | Create | AppTest fixture with schema YAML |
| `tests/functional/ui/test_data_contract_apptest.py` | Modify | New `Test_SchemaPendingEdits` class |

---

## Task 1: YAML helpers in `data_contract_yaml.py`

**Files:**
- Modify: `testgen/ui/views/data_contract_yaml.py`
- Test: `tests/unit/ui/test_schema_property_terms.py`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/ui/test_schema_property_terms.py`:

```python
"""
Unit tests for schema property YAML helpers.

pytest -m unit tests/unit/ui/test_schema_property_terms.py
"""
from __future__ import annotations

import sys
from types import ModuleType
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
```

- [ ] **Step 2: Run tests — expect import failures**

```bash
cd /Users/chris.bergh/PycharmProjects/dataops-testgen && source venv/bin/activate && pytest -m unit tests/unit/ui/test_schema_property_terms.py -v 2>&1 | head -40
```

Expected: `ImportError` — `_find_property` not found.

- [ ] **Step 3: Add helpers to `data_contract_yaml.py`**

After the final function `_build_pending_governance_edit` (line ~234), append:

```python
# ---------------------------------------------------------------------------
# Schema property helpers (pure, no Streamlit, no DB)
# ---------------------------------------------------------------------------

def _find_property(yaml_doc: dict, table_name: str, col_name: str) -> dict | None:
    """Return the property dict for col_name within table_name, or None if not found."""
    for table in yaml_doc.get("schema", []):
        if table.get("name") == table_name:
            for prop in table.get("properties", []):
                if prop.get("name") == col_name:
                    return prop
    return None


def _apply_pending_schema_edit(
    pending: dict,
    table_name: str,
    col_name: str,
    field: str,
    value: object,
) -> dict:
    """Add or replace a schema edit in the pending dict. Returns updated pending.

    value=None signals deletion.
    """
    schema = [
        e for e in pending.get("schema", [])
        if not (e["table"] == table_name and e["col"] == col_name and e["field"] == field)
    ]
    schema.append({"table": table_name, "col": col_name, "field": field, "value": value})
    return {**pending, "schema": schema}


def _apply_pending_schema_edits(doc: dict, pending_schema: list[dict]) -> None:
    """Apply pending schema edits in-place on the YAML doc.

    Each entry: {"table": str, "col": str, "field": str, "value": any | None}
    value=None deletes the field; any other value sets it.
    Updates x-testgen.user_schema_fields atomically.
    """
    x_testgen  = doc.setdefault("x-testgen", {})
    user_fields: dict[str, list[str]] = x_testgen.setdefault("user_schema_fields", {})

    for entry in pending_schema:
        table_name = entry["table"]
        col_name   = entry["col"]
        field      = entry["field"]
        value      = entry["value"]
        col_key    = f"{table_name}.{col_name}"

        prop: dict | None = _find_property(doc, table_name, col_name)
        if prop is None:
            for tbl in doc.get("schema", []):
                if tbl.get("name") == table_name:
                    tbl.setdefault("properties", []).append({"name": col_name})
                    prop = _find_property(doc, table_name, col_name)
                    break
            if prop is None:
                continue

        if value is None:
            prop.pop(field, None)
            current = user_fields.get(col_key, [])
            updated = [f for f in current if f != field]
            if updated:
                user_fields[col_key] = updated
            else:
                user_fields.pop(col_key, None)
        else:
            prop[field] = value
            current = user_fields.get(col_key, [])
            if field not in current:
                user_fields[col_key] = current + [field]
```

Also update `_pending_edit_count` (find the existing function and replace):

```python
def _pending_edit_count(pending: dict) -> int:
    """Total number of pending edits across all categories."""
    return (
        len(pending.get("governance", []))
        + len(pending.get("tests", []))
        + len(pending.get("schema", []))
        + len(pending.get("deletions", []))
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest -m unit tests/unit/ui/test_schema_property_terms.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add testgen/ui/views/data_contract_yaml.py tests/unit/ui/test_schema_property_terms.py
git commit -m "feat: add schema property YAML helpers and pending-edit state functions"
```

---

## Task 2: Schema term builder in `data_contract_props.py`

**Files:**
- Modify: `testgen/ui/views/data_contract_props.py`
- Test: `tests/unit/ui/test_schema_property_terms.py` (extend)

- [ ] **Step 1: Write failing tests for `_build_schema_terms`**

Add to `test_schema_property_terms.py` (after existing classes):

```python
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
```

- [ ] **Step 2: Run tests — expect import failure**

```bash
pytest -m unit tests/unit/ui/test_schema_property_terms.py::Test_BuildSchemaTerms -v 2>&1 | head -20
```

Expected: `ImportError` — `_build_schema_terms` not found.

- [ ] **Step 3: Add `_build_schema_terms` to `data_contract_props.py`**

Add the import at the top of `data_contract_props.py` (after existing imports):

```python
from testgen.ui.views.data_contract_yaml import _find_property
```

Add the function after `_extract_column_terms` (around line 431):

```python
def _build_schema_terms(yaml_doc: dict, table_name: str, col_name: str) -> list[dict]:
    """Return source='schema' term dicts for user-specified ODCS property fields."""
    user_fields: list[str] = (
        yaml_doc.get("x-testgen", {})
                .get("user_schema_fields", {})
                .get(f"{table_name}.{col_name}", [])
    )
    prop = _find_property(yaml_doc, table_name, col_name) or {}
    terms: list[dict] = []
    for field in user_fields:
        val = prop.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            display = ", ".join(str(v) for v in val)
        elif isinstance(val, bool):
            display = "true" if val else "false"
        else:
            display = str(val)
        if len(display) > 30:
            display = display[:29] + "…"
        terms.append({
            "name":    field,
            "source":  "schema",
            "verif":   "declared",
            "value":   display,
            "kind":    "static",
            "rule_id": f"schema|{table_name}|{col_name}|{field}",
        })
    return terms
```

Also add `"schema"` to `_SOURCE_META` (around line 66):

```python
_SOURCE_META: dict[str, tuple[str, str, str]] = {
    "ddl":        ("DDL",        "#f3f0fa", "#7c4dff"),
    "profiling":  ("Profiling",  "#e8f4fd", "#1976d2"),
    "governance": ("Governance", "#fffde7", "#ffa000"),
    "test":       ("Test",       "#f1f8e9", "#388e3c"),
    "monitor":    ("Monitor",    "#e8f5e9", "#00695c"),
    "schema":     ("Schema",     "#e0f2f1", "#00695c"),
}
```

- [ ] **Step 4: Wire `_build_schema_terms` into `_build_contract_props`**

In `_build_contract_props`, find the section that builds `cols_data` (around line 743). After the existing line:

```python
terms = _extract_column_terms(prop, col_rules, col_anomalies, col_refs, gov=gov)
```

Add:

```python
terms += _build_schema_terms(doc, table_name, col_name)
```

(Note: `doc` is the `yaml_doc` parameter already available in `_build_contract_props`.)

The function signature for `_build_contract_props` currently takes `doc: dict` — verify it's named `doc` at the call site and in the function body. Looking at the actual function, the parameter is named `doc` (confirmed from reading the file).

- [ ] **Step 5: Add `rule_id` to `static_terms` serialization**

Find the `static_terms` dict comprehension (around line 769):

```python
"static_terms": [
    {"name": c["name"], "value": c["value"], "source": c["source"], "verif": c["verif"]}
    for c in static_terms
],
```

Replace with:

```python
"static_terms": [
    {
        "name":    c["name"],
        "value":   c["value"],
        "source":  c["source"],
        "verif":   c["verif"],
        "rule_id": c.get("rule_id", ""),
    }
    for c in static_terms
],
```

- [ ] **Step 6: Run all schema term tests**

```bash
pytest -m unit tests/unit/ui/test_schema_property_terms.py -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add testgen/ui/views/data_contract_props.py tests/unit/ui/test_schema_property_terms.py
git commit -m "feat: add schema term builder and wire into contract props"
```

---

## Task 3: Schema edit dialog in `data_contract_dialogs.py`

**Files:**
- Modify: `testgen/ui/views/dialogs/data_contract_dialogs.py`

- [ ] **Step 1: Add imports**

At the top of `data_contract_dialogs.py`, where the `data_contract_yaml` imports are (around line 52):

```python
from testgen.ui.views.data_contract_yaml import (
    _apply_pending_governance_edit,
    _apply_pending_schema_edit,      # add this
    _apply_pending_schema_edits,     # add this
    _apply_pending_test_edit,
    _find_property,                  # add this
    _patch_yaml_governance,
)
```

- [ ] **Step 2: Add the dialog function**

Add `_schema_edit_dialog` near the end of the dialogs file, before the final save/cancel helpers. The full function:

```python
# ---------------------------------------------------------------------------
# Schema property editor dialog
# ---------------------------------------------------------------------------

_SCHEMA_CURATED: list[tuple[str, str]] = [
    ("tags",                 "string[]"),
    ("title",                "string"),
    ("unique",               "boolean"),
    ("pattern",              "string"),
    ("precision",            "integer"),
    ("scale",                "integer"),
    ("default",              "string"),
    ("encryptedName",        "string"),
    ("partitioned",          "boolean"),
    ("partitionKeyPosition", "integer"),
    ("references",           "string"),
]
_SCHEMA_CURATED_NAMES: frozenset[str] = frozenset(f for f, _ in _SCHEMA_CURATED)


@st.dialog("Schema Properties")
def _schema_edit_dialog(
    contract_id: str,
    table_group_id: str,  # noqa: ARG001  reserved for future governance fallback
    table_name: str,
    col_name: str,
) -> None:
    """Edit user-specified ODCS schema property fields for a single column."""
    yaml_key    = f"dc_yaml:{contract_id}"
    pending_key = f"dc_pending:{contract_id}"

    contract_yaml: str = st.session_state.get(yaml_key, "")
    doc: dict = {}
    try:
        parsed = yaml.safe_load(contract_yaml)
        doc = parsed if isinstance(parsed, dict) else {}
    except yaml.YAMLError:
        pass

    prop       = _find_property(doc, table_name, col_name) or {}
    user_fields: list[str] = (
        doc.get("x-testgen", {})
           .get("user_schema_fields", {})
           .get(f"{table_name}.{col_name}", [])
    )
    pending: dict = st.session_state.get(pending_key, {})

    # In-flight pending edits for this column take precedence over the YAML values.
    pending_for_col: dict[str, object] = {
        e["field"]: e["value"]
        for e in pending.get("schema", [])
        if e["table"] == table_name and e["col"] == col_name
    }

    def _cur(field: str) -> object:
        return pending_for_col.get(field, prop.get(field))

    st.caption(f"`{table_name}.{col_name}` — changes are staged and applied when you save the version.")

    # ── Curated fields ────────────────────────────────────────────────────────
    submitted: dict[str, object] = {}
    for field, ftype in _SCHEMA_CURATED:
        cur = _cur(field)
        if ftype == "boolean":
            is_on = st.toggle(field, value=bool(cur) if cur is not None else False, key=f"sch_dlg_{field}")
            # Toggle off on a previously-set value → delete; toggle on → True; no change → keep cur
            if is_on:
                submitted[field] = True
            elif cur is not None and cur is not False:
                submitted[field] = None  # was True, now off → delete
            else:
                submitted[field] = cur   # was None or False — unchanged
        elif ftype == "integer":
            cur_int = int(cur) if cur is not None else None
            raw = st.number_input(field, value=cur_int, step=1, key=f"sch_dlg_{field}")
            submitted[field] = int(raw) if raw is not None else None
        elif ftype == "string[]":
            cur_str = ", ".join(str(v) for v in cur) if isinstance(cur, list) else (str(cur) if cur else "")
            val = st.text_input(field, value=cur_str, placeholder="comma-separated", key=f"sch_dlg_{field}")
            if val.strip():
                submitted[field] = [v.strip() for v in val.split(",") if v.strip()]
            else:
                submitted[field] = None
        else:
            val = st.text_input(field, value=str(cur) if cur is not None else "", key=f"sch_dlg_{field}")
            submitted[field] = val.strip() if val.strip() else None

    # ── Custom fields ────────────────────────────────────────────────────────
    custom_fields = [f for f in user_fields if f not in _SCHEMA_CURATED_NAMES]
    st.subheader("Custom fields", divider="grey")
    surviving_customs: list[tuple[str, object]] = []
    for i, cf in enumerate(custom_fields):
        cur_v = _cur(cf)
        c1, c2, c3 = st.columns([3, 4, 1])
        new_key = c1.text_input("Field name", value=cf, key=f"sch_cf_k_{i}", label_visibility="collapsed")
        new_val = c2.text_input("Value", value=str(cur_v) if cur_v is not None else "",
                                key=f"sch_cf_v_{i}", label_visibility="collapsed")
        if not c3.button("✕", key=f"sch_cf_rm_{i}") and new_key.strip():
            surviving_customs.append((new_key.strip(), new_val.strip() if new_val.strip() else None))

    st.caption("Add a custom ODCS-compliant field (alphanumeric, dots, underscores).")
    nc1, nc2, _ = st.columns([3, 4, 1])
    new_field_key = nc1.text_input("New field name", value="", key="sch_cf_new_k",
                                   label_visibility="collapsed", placeholder="field name")
    new_field_val = nc2.text_input("New field value", value="", key="sch_cf_new_v",
                                   label_visibility="collapsed", placeholder="value")
    if new_field_key.strip():
        surviving_customs.append((new_field_key.strip(), new_field_val.strip() if new_field_val.strip() else None))

    # ── Save / Cancel ─────────────────────────────────────────────────────────
    save_col, cancel_col = st.columns(2)
    if save_col.button("Save to pending", type="primary", use_container_width=True):
        # Only record fields that actually changed
        for field, new_val in submitted.items():
            old_val = _cur(field)
            if new_val != old_val:
                pending = _apply_pending_schema_edit(pending, table_name, col_name, field, new_val)
                _apply_pending_schema_edits(doc, [{"table": table_name, "col": col_name, "field": field, "value": new_val}])

        # Custom field changes: delete removed ones, set survivors
        surviving_keys = {k for k, _ in surviving_customs}
        for cf in custom_fields:
            if cf not in surviving_keys:
                pending = _apply_pending_schema_edit(pending, table_name, col_name, cf, None)
                _apply_pending_schema_edits(doc, [{"table": table_name, "col": col_name, "field": cf, "value": None}])
        for cf_key, cf_val in surviving_customs:
            if cf_key not in _SCHEMA_CURATED_NAMES:
                old_v = _cur(cf_key)
                if cf_val != old_v:
                    pending = _apply_pending_schema_edit(pending, table_name, col_name, cf_key, cf_val)
                    _apply_pending_schema_edits(doc, [{"table": table_name, "col": col_name, "field": cf_key, "value": cf_val}])

        st.session_state[yaml_key]    = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        st.session_state[pending_key] = pending
        safe_rerun()

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()
```

The dialog requires `yaml` and `safe_rerun` — both already imported in `data_contract_dialogs.py`.

- [ ] **Step 3: Verify the app starts**

```bash
source venv/bin/activate && source local.env && python -c "from testgen.ui.views.dialogs.data_contract_dialogs import _schema_edit_dialog; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add testgen/ui/views/dialogs/data_contract_dialogs.py
git commit -m "feat: add schema property edit dialog with curated fields and custom escape hatch"
```

---

## Task 4: Python event wiring in `data_contract.py`

**Files:**
- Modify: `testgen/ui/views/data_contract.py`

- [ ] **Step 1: Add imports**

Add to the imports from `data_contract_yaml.py` (around line 59):

```python
from testgen.ui.views.data_contract_yaml import (
    _apply_pending_schema_edit,    # add
    _apply_pending_test_edit,
    _pending_edit_count,
)
```

Add to the imports from `data_contract_dialogs.py`:

```python
from testgen.ui.views.dialogs.data_contract_dialogs import (
    ...existing imports...,
    _schema_edit_dialog,            # add
)
```

- [ ] **Step 2: Add `on_schema_edit` event handler**

Inside the `render()` method, after `on_governance_edit` (around line 1033), add:

```python
def on_schema_edit(payload: dict) -> None:
    if not is_latest:
        return
    table_name = payload.get("tableName", "")
    col_name   = payload.get("colName", "")
    _schema_edit_dialog(contract_id, table_group_id, table_name, col_name)
```

- [ ] **Step 3: Update `on_bulk_delete_terms` to handle schema chips**

Schema chips have `rule_id` like `schema|orders|amount|tags`. The current handler tries to delete these from `quality` rules (no-op since they won't match), but they're never routed to the schema pending list. Fix:

Find `on_bulk_delete_terms` (around line 1078). Replace the function body with:

```python
def on_bulk_delete_terms(payload: dict) -> None:
    if not is_latest:
        return
    terms: list[dict] = payload.get("terms") or []
    if not terms:
        return

    # Intercept schema chip deletions before the generic handler
    schema_deletions = [t for t in terms if (t.get("rule_id") or "").startswith("schema|")]
    other_terms      = [t for t in terms if not (t.get("rule_id") or "").startswith("schema|")]

    if schema_deletions:
        current_pending: dict = st.session_state.get(pending_key, {})
        for t in schema_deletions:
            parts = t["rule_id"].split("|")  # ["schema", table, col, field]
            if len(parts) == 4:
                _, tbl, col, field = parts
                current_pending = _apply_pending_schema_edit(current_pending, tbl, col, field, None)
        st.session_state[pending_key] = current_pending

    if other_terms:
        _apply_term_deletions(
            other_terms, yaml_key, pending_key, table_group_id,
            snapshot_suite_id=version_record.get("snapshot_suite_id"),
        )
        st.session_state.pop(term_diff_key, None)

    safe_rerun()
```

- [ ] **Step 4: Add schema ghost chips to `pending_delete_terms` injection**

Find the section that builds `deletions_by_col` (around line 884). After the existing loops for `governance` and `tests`, add a schema loop:

```python
for e in pending.get("schema", []):
    if e.get("value") is None:
        snapshot = {"name": e["field"], "source": "schema", "verif": "declared"}
        deletions_by_col.setdefault((e["table"], e["col"]), []).append(snapshot)
```

- [ ] **Step 5: Add `pending_edit_schema_keys` prop**

Find where `pending_edit_gov_keys` is built (around line 982). After that block, add:

```python
_pending_schema_keys: list[str] = [
    f"schema|{e['table']}|{e['col']}|{e['field']}"
    for e in pending.get("schema", [])
    if e.get("value") is not None
]
props["pending_edit_schema_keys"] = _pending_schema_keys
```

- [ ] **Step 6: Register `SchemaEditClicked` in `event_handlers`**

Find the `event_handlers` dict (around line 1123). Add:

```python
"SchemaEditClicked": on_schema_edit,
```

- [ ] **Step 7: Verify import correctness**

```bash
source venv/bin/activate && source local.env && python -c "from testgen.ui.views.data_contract import DataContractPage; print('OK')"
```

Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add testgen/ui/views/data_contract.py
git commit -m "feat: wire schema edit event handler, bulk delete, ghost chips, and pending keys"
```

---

## Task 5: JavaScript — `data_contract.js`

**Files:**
- Modify: `testgen/ui/components/frontend/js/pages/data_contract.js`

All edits are within the single JS file. Make each sub-step as a focused edit.

- [ ] **Step 1: Add `schema` to `SOURCE_CLASS` and `SOURCE_LABEL`**

Find (around line 72):
```javascript
const SOURCE_CLASS = { ddl: 'ddl', profiling: 'prof', governance: 'gov', test: 'tst' };
const SOURCE_LABEL = { ddl: 'DDL', profiling: 'Profiling', governance: 'Governance', test: 'Test' };
```

Replace with:
```javascript
const SOURCE_CLASS = { ddl: 'ddl', profiling: 'prof', governance: 'gov', test: 'tst', schema: 'sch' };
const SOURCE_LABEL = { ddl: 'DDL', profiling: 'Profiling', governance: 'Governance', test: 'Test', schema: 'Schema' };
```

- [ ] **Step 2: Add `SchemaButton` component**

After `AddTestButton` (around line 277), insert:

```javascript
const SchemaButton = (col, tableName) => {
    const schTerms = [...col.static_terms].filter((c) => c.source === 'schema');
    const hasSch = schTerms.length > 0;
    const label = hasSch ? `◈ Schema (${schTerms.length})` : '◈ + Schema';
    return withTooltip(
        div(
            {
                class: 'gov-btn gov-btn--schema',
                onclick: (e) => {
                    e.stopPropagation();
                    emitEvent('SchemaEditClicked', {
                        payload: { tableName, colName: col.name },
                    });
                },
            },
            label,
        ),
        { text: hasSch ? 'Edit ODCS schema properties' : 'Add ODCS schema properties', position: 'bottom' },
    );
};
```

- [ ] **Step 3: Update `ColumnRow` to include `SchemaButton`**

Find `ColumnRow` (around line 279). Change the function signature and add `SchemaButton`:

```javascript
const ColumnRow = (col, tableName, showAddTest = false, showSchema = false) => {
    const statusIcon = col.status === 'failing'
        ? mat('cancel', 14, 'col-status-fail')
        : col.status === 'warning'
        ? mat('warning', 14, 'col-status-warn')
        : '';
    return div(
        { class: 'col-row' },
        div(
            { class: 'col-header' },
            span({ class: 'col-name-link' }, col.name, statusIcon ? ' ' : '', statusIcon),
            span({ class: 'col-type' }, col.type || ''),
            col.is_pk ? span({ class: 'key-badge' }, mat('key', 13), ' PK') : '',
            col.is_fk ? span({ class: 'key-badge' }, mat('call_made', 13), ' FK') : '',
            GovernanceButton(col, tableName),
            showAddTest  ? AddTestButton(col, tableName)  : '',
            showSchema   ? SchemaButton(col, tableName)   : '',
        ),
        div(
            { class: 'terms-row' },
            ...col.static_terms.map((c) => TermChip(c, tableName, col.name)),
            ...col.live_terms.map((c) => TermChip(c, tableName, col.name)),
            ...(col.pending_delete_terms || []).map((c) => DeletedTermChip(c)),
        ),
    );
};
```

- [ ] **Step 4: Pass `showSchema` through `TableSection` and call site**

Find `TableSection` (around line 324). Add `showSchema = false` parameter and thread it through:

```javascript
const TableSection = (tableData, startOpen = false, showAddTest = false, showSchema = false) => {
    // ... existing code ...
    // In the columns.map call, change:
    ...tableData.columns.map((col) => ColumnRow(col, tableData.name, showAddTest, showSchema)),
```

Find the two `div(...tables.map(...))` call sites (around lines 667, 710) and update:

```javascript
// line ~667:
return div(...tables.map((t, i) => TableSection(t, i === 0, showAddTest, showSchema)));
// line ~710:
return div(...filtered.map((t, i) => TableSection(t, i === 0, showAddTest, showSchema)));
```

Find where `showAddTest` is derived from `versionInfo` (around line 1867) and add `showSchema`:

```javascript
const showAddTest = !!(versionInfo.snapshot_suite_id && versionInfo.is_latest);
const showSchema  = !!(versionInfo.is_latest);
```

And update the `TermsDetail` function signature and the `TableSection` calls within it.

Find `TermsDetail` definition (around line 389):

```javascript
const TermsDetail = (tables, activeFilter, showAddTest = false, showSchema = false) => {
```

- [ ] **Step 5: Add Schema filter pill**

Find the filter pills array (around line 586):

```javascript
...['db_enforced', 'tested', 'monitored', 'observed', 'declared'].map((verif) => {
```

After this entire `.map(...)` block (after the closing `),`), add the Schema pill:

```javascript
span(
    {
        class: () => `filter-pill filter-pill--verif filter-pill--badge-decl ${activeFilter.val === 'schema' ? 'active' : ''}`,
        onclick: () => { activeFilter.val = 'schema'; },
    },
    mat('schema', 12, 'filter-pill-icon'), ' Schema',
),
```

- [ ] **Step 6: Update `termFilter` to handle schema source filter**

In `getFilteredTables` (around line 478), the `termFilter` currently ends with `return c.verif === filter;`. Change it to:

```javascript
const termFilter = (c) => {
    if (filter === 'uncovered') return false;
    if (filter === 'failing')   return c.kind === 'live' && FAILING_STATUS.has(c.status);
    if (filter === 'anomalies') return c.kind === 'live' && c.source === 'profiling';
    if (filter === 'schema')    return c.source === 'schema';
    return c.verif === filter;
};
```

- [ ] **Step 7: Add Schema SourceRow to `TermsHelpPanel`**

In `TermsHelpPanel` (around line 1564), after the Test `SourceRow` call:

```javascript
SourceRow('tst',  'Test',       'Tested',
    'Active quality rule — format check, LOV match, range bound, custom SQL assertion — executes on every test run.'),
```

Add:

```javascript
SourceRow('sch',  'Schema',     'Declared',
    'Manually specified ODCS standard fields — tags, title, uniqueness, value pattern, precision/scale, and other property-level annotations not derived from DDL or profiling.'),
```

- [ ] **Step 8: Sync `pending_edit_schema_keys` in `DataContract`**

In `DataContract` (around line 1829), find the `van.derive` that syncs pending edit keys:

```javascript
van.derive(() => {
    const ruleIds = getValue(props.pending_edit_rule_ids) || [];
    const govKeys = getValue(props.pending_edit_gov_keys) || [];
    const next = new Set([...ruleIds, ...govKeys]);
```

Add schema keys:

```javascript
van.derive(() => {
    const ruleIds    = getValue(props.pending_edit_rule_ids)    || [];
    const govKeys    = getValue(props.pending_edit_gov_keys)    || [];
    const schemaKeys = getValue(props.pending_edit_schema_keys) || [];
    const next = new Set([...ruleIds, ...govKeys, ...schemaKeys]);
```

- [ ] **Step 9: Add CSS for schema chip and button**

In the embedded stylesheet (around line 2309), after the existing `.term-chip.gov` line:

```css
.term-chip.sch  { border-color: rgba(0,150,136,0.3);  background: rgba(0,150,136,0.07);  }
.term-chip.sch  .term-chip__src { color: #00796b; }
```

After `.chip-tst` (around line 3044):

```css
.chip-sch  { background: rgba(0,150,136,0.12);  color: #00796b; border: 1px solid rgba(0,150,136,0.3);  }
```

After `.gov-btn:hover` (around line 2259):

```css
.gov-btn--schema { color: #00796b; border-color: rgba(0,150,136,0.4); }
.gov-btn--schema:hover { color: #004d40; border-color: #00796b; background: rgba(0,150,136,0.08); }
```

- [ ] **Step 10: Verify JS syntax**

```bash
node --input-type=module < testgen/ui/components/frontend/js/pages/data_contract.js 2>&1 | head -20
```

Expected: no output (no syntax errors). If there are errors, fix them before committing.

- [ ] **Step 11: Commit**

```bash
git add testgen/ui/components/frontend/js/pages/data_contract.js
git commit -m "feat: add schema chips, SchemaButton, filter pill, and TermsHelpPanel entry"
```

---

## Task 6: Functional tests (AppTest)

**Files:**
- Create: `tests/functional/ui/apps/data_contract_schema_terms.py`
- Modify: `tests/functional/ui/test_data_contract_apptest.py`

- [ ] **Step 1: Create the fixture app script**

Create `tests/functional/ui/apps/data_contract_schema_terms.py`:

```python
"""
AppTest fixture — Data Contract page with schema terms in the YAML.
"""
from __future__ import annotations

from tests.functional.ui.apps._dc_app_common import (
    TG_ID, CONTRACT_ID, VERSION_1,
    make_mock_tg, make_mock_auth, make_mock_version_svc, make_minimal_term_diff,
    make_default_patches, render_page,
)
import streamlit as st

SCHEMA_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-contract-002
schema:
  - name: orders
    properties:
      - name: amount
        physicalType: "numeric(10,2)"
        tags: [billing, finance]
        title: Invoice Amount
        unique: false
quality: []
x-testgen:
  user_schema_fields:
    orders.amount: [tags, title, unique]
"""

VERSION_WITH_SCHEMA = {**VERSION_1, "contract_yaml": SCHEMA_YAML}

_mock_tg   = make_mock_tg()
_mock_auth = make_mock_auth()
_mock_vsvc = make_mock_version_svc()
_term_diff = make_minimal_term_diff()

st.session_state["auth"] = _mock_auth
st.query_params["contract_id"] = CONTRACT_ID

render_page(make_default_patches(_mock_tg, _term_diff, _mock_vsvc, current_version=VERSION_WITH_SCHEMA))
```

- [ ] **Step 2: Write the functional test class**

Add to `test_data_contract_apptest.py` a new helper function and class. First add the app path variable with the others at the top of the file:

```python
_APP_SCHEMA = str(pathlib.Path(__file__).parent / "apps" / "data_contract_schema_terms.py")
```

Add helper:
```python
def _at_schema() -> AppTest:
    return AppTest.from_file(_APP_SCHEMA, default_timeout=15)
```

Add the test class:

```python
class Test_SchemaPendingEdits:
    """Schema pending edits — pending count, ghost chips, warning banner."""

    def _inject_schema_pending(self, at: AppTest) -> AppTest:
        """Pre-inject one schema pending edit via session state before running."""
        at.session_state["dc_pending:" + CONTRACT_ID] = {
            "schema": [{"table": "orders", "col": "amount", "field": "pattern", "value": r"^\d+$"}],
        }
        return at

    def test_page_renders_with_schema_yaml(self):
        at = _at_schema().run()
        assert not at.exception

    def test_schema_pending_edit_increments_pending_count(self):
        at = _at_schema()
        self._inject_schema_pending(at)
        at.run()
        assert not at.exception
        all_text = _all_text(at)
        # pending count > 0 means Save button shows count or warning banner appears
        assert "1" in all_text or "unsaved" in all_text.lower()

    def test_warning_banner_present_when_schema_edits_pending(self):
        at = _at_schema()
        self._inject_schema_pending(at)
        at.run()
        warnings = [w.value for w in at.warning]
        assert any("unsaved" in w.lower() or "pending" in w.lower() or "change" in w.lower()
                   for w in warnings)

    def test_warning_banner_absent_when_no_schema_edits(self):
        at = _at_schema().run()
        assert not at.exception
        # No pending edits → no warning banner about unsaved changes
        warnings = [w.value for w in at.warning]
        assert not any("unsaved" in w.lower() for w in warnings)

    def test_zero_schema_edits_no_count_suffix(self):
        at = _at_schema().run()
        assert not at.exception
        all_text = _all_text(at)
        # Save button should not show a count > 0
        assert "unsaved" not in all_text.lower()

    def test_multiple_schema_edits_counted_correctly(self):
        at = _at_schema()
        at.session_state["dc_pending:" + CONTRACT_ID] = {
            "schema": [
                {"table": "orders", "col": "amount", "field": "pattern", "value": r"^\d+$"},
                {"table": "orders", "col": "amount", "field": "scale",   "value": 2},
            ],
        }
        at.run()
        assert not at.exception
        all_text = _all_text(at)
        assert "2" in all_text or "unsaved" in all_text.lower()
```

- [ ] **Step 3: Run functional tests**

```bash
pytest -m functional tests/functional/ui/test_data_contract_apptest.py::Test_SchemaPendingEdits -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/functional/ui/apps/data_contract_schema_terms.py tests/functional/ui/test_data_contract_apptest.py
git commit -m "test: add functional tests for schema pending edits"
```

---

## Self-Review Checklist

- [x] `_find_property` defined in `data_contract_yaml.py` and referenced consistently in props + dialog
- [x] `rule_id` uses `|` separator (`schema|table|col|field`) — no colons — consistent in `_build_schema_terms`, `on_bulk_delete_terms` parser, and JS `_termInfoByKey`
- [x] `_pending_edit_count` includes `schema` key
- [x] `static_terms` serialization includes `rule_id` (schema chips need it for TermChip key registration)
- [x] `on_bulk_delete_terms` intercepts `schema|` prefix before treating rule_id as a quality rule id
- [x] Schema ghost chips injected into `pending_delete_terms` via `deletions_by_col`
- [x] `pending_edit_schema_keys` synced to JS for dashed-border dirty-chip highlighting
- [x] `SchemaButton` hidden on historical versions (`showSchema = !!(versionInfo.is_latest)`)
- [x] Schema chip body click on historical versions: `TermChip` already guards `hasDetail` and calls `TermDetailClicked`; `on_term_detail` returns early when `not is_latest` for non-read-only sources — but schema chips have `verif='declared'` which routes to `_term_edit_dialog` not `_term_read_dialog`. **Fix needed:** in `on_term_detail`, add a guard for `source === 'schema'` on non-latest to call `_term_read_dialog` (read-only view) or do nothing. Add to `on_term_detail`:
  ```python
  elif source == "schema":
      if is_latest:
          _schema_edit_dialog(contract_id, table_group_id, table_name, col_name)
      # else: inert on historical versions
  ```
- [x] `TermsDetail` signature updated to accept `showSchema` and threads it to `TableSection`
- [x] CSS: `.term-chip.sch`, `.chip-sch`, `.gov-btn--schema` all added
- [x] `TermsHelpPanel`: Schema SourceRow added after Test

**Note on `on_term_detail` fix:** This is required for correctness. Add it in Task 4 Step 2 (alongside `on_schema_edit`):

```python
def on_term_detail(payload: dict) -> None:
    term       = payload.get("term", {})
    table_name = payload.get("tableName", "")
    col_name   = payload.get("colName", "")
    source = term.get("source", "")
    verif  = term.get("verif", "")
    term_name = term.get("name", "")
    snapshot_suite_id = version_record.get("snapshot_suite_id")
    if not is_latest:
        _term_read_dialog(term, table_name, col_name, contract_id, yaml_key)
    elif source == "schema":
        _schema_edit_dialog(contract_id, table_group_id, table_name, col_name)
    elif source == "monitor":
        _monitor_term_dialog(term.get("rule", {}), term_name, table_name, col_name)
    elif source == "test":
        rule_id = term.get("rule_id", "")
        if rule_id:
            from testgen.ui.views.test_definitions import show_test_form_by_id
            show_test_form_by_id(rule_id)
        else:
            _test_term_dialog(term, table_name, col_name, project_code, yaml_key, contract_id)
    elif source == "governance" and verif == "declared":
        _term_edit_dialog(term, table_name, col_name, contract_id, yaml_key)
    else:
        _term_read_dialog(term, table_name, col_name, contract_id, yaml_key)
```

This replaces the existing `on_term_detail` in Task 4.
