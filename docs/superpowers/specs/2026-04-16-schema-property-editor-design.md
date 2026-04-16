# Schema Property Editor — Design Spec

**Date:** 2026-04-16
**Status:** Approved

## Overview

Users can currently edit governance fields (description, CDE, PII, tag fields) from the data contract UI. This feature adds a new term source — **Schema** — that lets users manually set any ODCS v3.1.0 property-level field that TestGen does not auto-derive from DDL or profiling. Full create, update, and delete of these user-specified properties is supported, with the same pending-edits staging pattern used by governance and test edits.

Schema edits are only available on the **latest (editable) version** of a contract. Historical (read-only) versions suppress the Schema button and disable chip ✕ deletion.

---

## Scope

**In scope:**
- Add / edit / delete manually specified ODCS schema property fields per column
- Curated form for well-known ODCS fields (tags, title, unique, pattern, precision, scale, default, encryptedName, partitioned, partitionKeyPosition, references)
- Custom escape hatch for arbitrary ODCS-compliant field names
- Schema chips rendered in the terms grid alongside DDL / profiling / governance / test chips
- "◈ + Schema" button in the column header row **below** existing Governance and Add test buttons (vertical stack)
- "Schema" filter pill in the filter bar
- Schema source row added to the "What are contract terms?" help panel
- Schema edits join the pending-edits staging flow (dc_pending.schema); count included in save button label and warning banner
- YAML-only storage (no DB column); fields written directly into `schema[].properties[]` and tracked in `x-testgen.user_schema_fields`
- Individual chip ✕ deletion using the existing term-deletion flow
- Unit tests and AppTest functional tests

**Out of scope:**
- Editing auto-derived fields (physicalType, logicalType, required, examples)
- DB sync for schema property values
- Overriding governance fields (description, CDE, PII) via this dialog — those stay in the governance dialog
- Bulk schema property editing across multiple columns at once
- Schema edits on historical (read-only) versions — the Schema button and chip ✕ are hidden on non-latest versions
- Document-level ODCS fields (`description.purpose`, `domain`, `status`, `version`) — these are top-level YAML fields, not property-level. Editing them is a separate future feature: a document metadata dialog in the contract toolbar targeting the root YAML dict via a new `dc_pending.document` key and `_apply_pending_document_edits`. The pending-edits pattern is identical; only the target path changes.

---

## Architecture

### Files Changed

| File | Change |
|---|---|
| `testgen/ui/components/frontend/js/pages/data_contract.js` | New `SchemaButton` component; new `chip-sch` chip style; new "Schema" filter pill (filters by `source === 'schema'`); new `SourceRow` in `TermsHelpPanel`; filter logic special-cases `source` check for schema |
| `testgen/ui/views/data_contract.py` | New `_build_schema_terms(yaml_doc, table_name, col_name)` → produces `source='schema'` terms; new `SchemaEditClicked` event handler; `pending_ct` includes `len(pending.get("schema", []))` |
| `testgen/ui/views/dialogs/data_contract_dialogs.py` | New `_schema_edit_dialog(contract_id, table_group_id, table_name, col_name)` — Option A form (curated fields + custom escape hatch); loads current values from `st.session_state` YAML |
| `testgen/ui/views/data_contract_yaml.py` | New `_apply_pending_schema_edits(doc, pending_schema)` — writes/deletes fields in `schema[].properties[]` and updates `x-testgen.user_schema_fields` tracker; new `_find_property(yaml_doc, table_name, col_name)` pure helper |
| `testgen/ui/queries/data_contract_queries.py` | `_persist_pending_edits` flushes `pending["schema"]` by calling `_apply_pending_schema_edits` then serializing YAML — no DB write |
| `tests/unit/ui/test_schema_property_terms.py` | Unit tests (new file) |
| `tests/functional/ui/test_data_contract_apptest.py` | New `Test_SchemaPendingEdits` test class |

---

## Data Model

### Storage: YAML-only

Schema properties live exclusively in the contract version YAML. They are written into the standard ODCS `schema[].properties[]` section as top-level fields. A tracker section records which fields were user-specified (vs. auto-derived) so `_build_schema_terms` can identify them unambiguously:

```yaml
schema:
  - name: orders
    properties:
      - name: amount
        physicalType: "numeric(10,2)"   # auto-derived — NOT a schema chip
        required: true                   # auto-derived — NOT a schema chip
        tags: [billing, finance]         # user-specified — schema chip
        title: Invoice Amount            # user-specified — schema chip
        unique: false                    # user-specified — schema chip
        pattern: '^\d+(\.\d{2})?$'      # user-specified — schema chip

x-testgen:
  user_schema_fields:
    orders.amount:       [tags, title, unique, pattern]
    orders.customer_id:  [references]
```

The `x-testgen.user_schema_fields` map is the authoritative record of which fields were user-added. It is updated atomically with the field values by `_apply_pending_schema_edits`.

---

## ODCS Field Catalog (Curated Form)

All fields are optional. Absence means the field is not included in the YAML.

| Field | Type | Input Widget | Description |
|---|---|---|---|
| `tags` | string[] | Comma-separated text | Searchable labels, e.g. `billing, finance` |
| `title` | string | Text input | Human-readable column name |
| `unique` | boolean | Toggle | Whether column values are unique |
| `pattern` | string | Text input | Regex constraint, e.g. `^\d+(\.\d{2})?$` |
| `precision` | integer | Number input | Total digits for numeric columns |
| `scale` | integer | Number input | Decimal digits for numeric columns |
| `default` | string | Text input | Default value expression |
| `encryptedName` | string | Text input | Obfuscated column name for masking |
| `partitioned` | boolean | Toggle | Whether this is a partition key |
| `partitionKeyPosition` | integer | Number input | Position among partition keys (1-based) |
| `references` | string | Text input | Foreign key reference, e.g. `customers.id` |

Below the curated section: a dynamic key/value list for **custom fields**. Each row has a field-name input, a value input, and an ✕ remove button. The "+ Add another" link appends a new blank row. Any field name is accepted here as long as it is a valid ODCS identifier (alphanumeric + dots/underscores).

Clearing a curated field's value (empty string / toggling off a boolean that was previously on) is treated as a delete for that field.

---

## UI Design

### Column Header

The `col-header` element uses a vertical stack (flex-direction: column). The action buttons appear as a stacked group below the column name / type row, in this order:

```
[col-name]  [col-type]
[🏷 Governance]
[+ Add test]
[◈ + Schema]          ← new, bottom of stack
```

The Schema button uses the same `gov-btn` CSS class pattern, styled teal (`chip-sch` palette). It is only rendered when the contract is on its latest (editable) version. When at least one schema property exists for the column, the button label changes to `◈ Schema (N)` where N is the count of user-specified fields, mirroring the existing `GovernanceButton` pattern.

### Schema Chips

Schema property chips appear in `static_terms` (not `live_terms`) since they have no runtime test result. Each chip:
- Color: teal (`background: var(--teal-bg); border-color: var(--teal-border); color: var(--teal)`)
- Label: `{field}: {display_value}` — for lists, values are comma-joined and truncated at 30 chars with `…`
- Has an ✕ button — clicking emits `BulkDeleteTermsClicked` with `source: 'schema'` and the chip's `rule_id`
- Clicking the chip body (not ✕) opens `_schema_edit_dialog` — only on the **latest (editable) version**; chip body is inert on historical versions
- Pending (not-yet-saved) chips render with a dashed border

### Filter Pill

Added after the Declared pill in the filter bar:

```
All  ⚖ Enforced  📷 Observed  🏷 Declared  ⚡ Tested  📡 Monitored  ◈ Schema
```

When `activeFilter.val === 'schema'`, the term filter predicate checks `term.source === 'schema'` rather than `term.verif`. This is the only filter that uses source rather than verif.

### Help Panel

New `SourceRow` added after Test in the Term Sources table:

| Source | Evidence Level | What it provides |
|---|---|---|
| **Schema** | Declared | Manually specified ODCS standard fields — tags, title, uniqueness, value pattern, precision/scale, and other property-level annotations not derived from DDL or profiling. |

No new Verification Level row is needed; schema terms reuse the existing `declared` verif level.

---

## Pending Edits

### dc_pending.schema Structure

```python
pending["schema"] = [
    # Set or update a field
    {"table": "orders", "col": "amount",      "field": "tags",    "value": ["billing", "finance"]},
    {"table": "orders", "col": "amount",      "field": "unique",  "value": False},
    {"table": "orders", "col": "customer_id", "field": "references", "value": "customers.id"},
    # Delete a field (value=None)
    {"table": "orders", "col": "amount",      "field": "pattern", "value": None},
]
```

Each `(table, col, field)` triple is unique in the list. When the user edits the same field twice, the old entry is replaced. `value=None` signals deletion.

### Pending Count

```python
pending_ct = (
    len(pending.get("governance", []))
    + len(pending.get("tests", []))
    + len(pending.get("schema", []))
    + len(pending.get("deletions", []))
)
```

The save button label and warning banner already compute `pending_ct` from this expression — no structural change needed, only adding the `schema` key to the sum.

---

## Import Behavior

When a user uploads a YAML via the Import YAML flow, the imported document may already contain `x-testgen.user_schema_fields` entries (e.g., exported from TestGen earlier, then edited externally).

The import handler (`run_import_contract`) must:
1. Preserve the `x-testgen.user_schema_fields` section from the uploaded YAML as-is
2. Not attempt to reconcile it with DB state — schema property fields are YAML-only

If the uploaded YAML has schema properties for a column but no `x-testgen.user_schema_fields` entry for that column, those properties are treated as auto-derived (not shown as schema chips). The user may re-add them via the Schema dialog to register them as user-specified.

---

## Schema Term Building

### _build_schema_terms(yaml_doc, table_name, col_name)

Location: `testgen/ui/views/data_contract.py`

```python
def _build_schema_terms(yaml_doc: dict, table_name: str, col_name: str) -> list[dict]:
    """Return source='schema' term dicts for user-specified ODCS property fields."""
    user_fields: list[str] = (
        yaml_doc.get("x-testgen", {})
                .get("user_schema_fields", {})
                .get(f"{table_name}.{col_name}", [])
    )
    prop = _find_property(yaml_doc, table_name, col_name) or {}
    terms = []
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
            "name": field,
            "source": "schema",
            "verif": "declared",
            "value": display,
            "rule_id": f"schema|{table_name}|{col_name}|{field}",
        })
    return terms
```

These terms are appended to `col["static_terms"]` when building the props sent to the VanJS component, after DDL/profiling/governance terms.

### _apply_pending_schema_edits(doc, pending_schema)

Location: `testgen/ui/views/data_contract_yaml.py`

For each entry in `pending_schema`:
1. Locate `schema[table].properties[col]` in the doc (create path if missing)
2. If `value is None`: delete the field from the property dict
3. Otherwise: set `prop[field] = value`
4. Update `x-testgen.user_schema_fields["{table}.{col}"]`:
   - Remove the field if `value is None`
   - Append the field if not already present
   - If the list is now empty, delete the entire `"{table}.{col}"` key from `user_schema_fields`

### Deletion via ✕ Chip

When the user clicks ✕ on a schema chip, the frontend emits `BulkDeleteTermsClicked` with:

```json
{
  "terms": [{"source": "schema", "rule_id": "schema|orders|amount|tags", "table": "orders", "col": "amount"}]
}
```

The `rule_id` uses `|` as separator (not `:`) to avoid collisions with table or column names that contain colons. The Python handler splits on `|` to extract `(_, table, col, field)` and appends `{"table": …, "col": …, "field": …, "value": None}` to `dc_pending["schema"]`. The chip immediately renders with a dashed border as a `pending_delete_term`. On save, `_apply_pending_schema_edits` removes the field from YAML.

The ✕ button is only rendered when the contract is on its latest (editable) version. Historical versions render chips without a ✕.

---

## Dialog: _schema_edit_dialog

Decorator: `@st.dialog("Schema Properties")`

Signature: `_schema_edit_dialog(contract_id: str, table_group_id: str, table_name: str, col_name: str) -> None`

No `current_props` parameter — the dialog loads current values directly from the cached YAML in session state.

Behavior:
1. Load current YAML from `st.session_state[f"dc_yaml:{contract_id}"]`
2. Call `_find_property(yaml_doc, table_name, col_name)` to get the current property dict (may be `{}`)
3. Read `x-testgen.user_schema_fields[f"{table_name}.{col_name}"]` to know which fields are already user-specified
4. Render curated fields section — each field pre-populated with its current value (or empty/off)
5. Render custom fields section — rows for any `user_schema_fields` entries not in the curated list, plus a blank row for new entries
6. On "Save to pending": build diff between current and submitted values; append changes to `dc_pending["schema"]`; call `_apply_pending_schema_edits` on the in-memory YAML; update `st.session_state[yaml_key]`; rerun
7. On "Cancel": rerun without changes

The dialog is opened via `SchemaEditClicked` event from the frontend, following the same `event_handlers` pattern as `GovernanceEditClicked`.

---

## Helper: _find_property

```python
def _find_property(yaml_doc: dict, table_name: str, col_name: str) -> dict | None:
    """Return the property dict for col_name within table_name, or None if not found."""
    for table in yaml_doc.get("schema", []):
        if table.get("name") == table_name:
            for prop in table.get("properties", []):
                if prop.get("name") == col_name:
                    return prop
    return None
```

Used by both `_build_schema_terms` and `_schema_edit_dialog`. When `_apply_pending_schema_edits` needs to set a field on a column whose property dict does not yet exist, it creates the path (adds to `schema[table].properties[]`).

---

## Testing

### Unit Tests — test_schema_property_terms.py

```
tests/unit/ui/test_schema_property_terms.py
```

- `_build_schema_terms` with `user_schema_fields` populated → returns correct term objects (name, source, verif, value, rule_id)
- `_build_schema_terms` with empty / missing `user_schema_fields` → returns `[]`
- `_build_schema_terms` list-valued field (`tags`) → value is comma-joined string
- `_build_schema_terms` boolean field (`unique: false`) → value is `"false"` string
- `_build_schema_terms` long value truncated at 30 chars with `…`
- `_apply_pending_schema_edits` SET → field appears in YAML property and in tracker
- `_apply_pending_schema_edits` DELETE (value=None) → field removed from YAML property and from tracker
- `_apply_pending_schema_edits` custom field (escape hatch) → stored alongside curated fields
- `_apply_pending_schema_edits` idempotent: applying same value twice leaves tracker with one entry
- `pending_ct` sums schema edits correctly alongside governance/test/deletion counts

### Functional Tests — Test_SchemaPendingEdits (AppTest)

New class in `tests/functional/ui/test_data_contract_apptest.py`:

- Page with schema terms in session-state YAML renders without exception
- Schema pending edit injected via `dc_test_inject_pending` → save button label includes count
- Warning banner appears when schema edits are pending
- Warning banner absent when no schema edits present
- Pending count in banner matches number of staged schema changes
- Schema chip ✕ deletion adds `value=None` entry to `dc_pending.schema`
- Zero schema edits → save button shows no count suffix
- Schema filter pill text present in rendered filter bar markdown
- Help panel text includes "Schema" in the Term Sources section
