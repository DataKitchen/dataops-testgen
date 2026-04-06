# Data Contract — Implementation Plan

> Created: 2026-04-05 | Last updated: 2026-04-05  
> Design reference: `.ai/contract-lifecycle-design.md`

Each phase is a shippable unit. Later phases depend on earlier ones as noted. Tests are written in the same phase as the code they cover.

## Implementation Status

| Phase | Status | Notes |
|---|---|---|
| 0 — Core UI (pre-plan) | ✅ Done | `data_contract.py`, `data_contract.js`, export/import commands, DB migrations 0180–0183 |
| 0a — Coverage Matrix redesign | ✅ Done | 5-tier columns (DB/Tested/Mon/Obs/Decl), ClaimCountsBar at top, Gap Analysis tab removed, ts-name/ts-meta headers, table-level monitor rows |
| 0b — Code review fixes (round 1–2) | ✅ Done | HTML escaping (`html.escape`), SQL injection in `_fetch_anomalies` fixed, shared `_pii_flag_to_classification`, staleness SQL column names fixed, composite FK ref matching fixed, logger standardized |
| 1 — DB schema | 🔲 Not started | `0184_incremental_upgrade.sql` — `data_contracts` table + staleness columns |
| 2 — Contract version data layer | 🔲 Not started | `contract_versions.py` |
| 3 — Staleness detection hooks | 🔲 Not started | Hooks into profiling + test definition changes |
| 4 — Staleness diff computation | 🔲 Not started | `contract_staleness.py` (structure exists but diff logic is stub) |
| 5 — Pending edit model | 🔲 Not started | Edit dialogs write to session state only |
| 6 — Page load from saved snapshot | 🔲 Not started | Replace `_capture_yaml` with `load_contract_version` |
| 7 — First-time flow | 🔲 Not started | Prerequisites gate → preview → save as v0 |
| 8 — Staleness banner + diff panel | 🔲 Not started | Banner + `_review_changes_panel` dialog |
| 9 — Version picker + historic view | 🔲 Not started | Dropdown + read-only mode |
| 10 — Remove old lifecycle artifacts | 🔲 Not started | Dead `_STATUS_COLOR`, old `contract_version`/`contract_status` writes |
| 11 — Frontend (VanJS) updates | 🔲 Not started | Version display, picker, staleness indicator |
| 12 — Full test suite | 🔲 Partial | `Test_ClaimCountConsistency` (8 tests) written; staleness diff tests started |

---

---

## Phase 1 — Database schema

**Goal:** Get the right tables and columns on disk. Nothing else can proceed without this.

### Migration 0184 — `data_contracts` table + staleness columns

```sql
SET SEARCH_PATH TO {SCHEMA_NAME};

-- Versioned contract snapshots
CREATE TABLE IF NOT EXISTS data_contracts (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    table_group_id  UUID        NOT NULL REFERENCES table_groups(id) ON DELETE CASCADE,
    version         INTEGER     NOT NULL,
    saved_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    label           TEXT,
    contract_yaml   TEXT        NOT NULL,
    UNIQUE (table_group_id, version)
);

CREATE INDEX IF NOT EXISTS idx_data_contracts_tg_version
    ON data_contracts (table_group_id, version DESC);

-- Staleness tracking on table_groups
ALTER TABLE table_groups
    ADD COLUMN IF NOT EXISTS contract_stale           BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS last_contract_save_date  TIMESTAMPTZ;

-- The contract_version (VARCHAR) and contract_status columns added in 0180
-- are superseded by data_contracts.version and are no longer used.
-- They are left in place to avoid breaking existing rows but should be
-- treated as deprecated. Do not write to them from new code.
COMMENT ON COLUMN table_groups.contract_version IS 'DEPRECATED — use data_contracts.version';
COMMENT ON COLUMN table_groups.contract_status  IS 'DEPRECATED — unused in versioned model';
```

**Files changed:**
- `testgen/template/dbupgrade/0184_incremental_upgrade.sql` — new file

**Tests:**
- Verify migration applies cleanly on a fresh schema
- Verify `data_contracts` unique constraint (same `table_group_id` + `version` rejected)

---

## Phase 2 — Contract version data layer

**Goal:** A clean Python API for saving, loading, and listing contract versions. No UI changes yet.

### New file: `testgen/commands/contract_versions.py`

```
save_contract_version(table_group_id, yaml_content, label=None) -> int
    1. INSERT INTO data_contracts (table_group_id, version, saved_at, label, contract_yaml)
       SELECT :tg_id,
              COALESCE(MAX(version), -1) + 1,
              NOW(), :label, :yaml
       FROM data_contracts
       WHERE table_group_id = :tg_id
       RETURNING version
       -- Single atomic statement: no SELECT-then-INSERT race condition.
       -- The UNIQUE(table_group_id, version) constraint is a safety net
       -- but should never be hit with this approach.
    2. UPDATE table_groups SET
           contract_stale = FALSE,
           last_contract_save_date = NOW()
       WHERE id = :tg_id
    3. Return the version number from the RETURNING clause.

load_contract_version(table_group_id, version=None) -> dict | None
    If version is None: SELECT WHERE version = MAX(version) for this table_group_id
    Else: SELECT WHERE table_group_id = ? AND version = ?
    Returns {"version": int, "saved_at": datetime, "label": str|None,
             "contract_yaml": str} or None if not found.

list_contract_versions(table_group_id) -> list[dict]
    SELECT version, saved_at, label FROM data_contracts
    WHERE table_group_id = ? ORDER BY version DESC
    Returns list of {"version": int, "saved_at": datetime, "label": str|None}

has_any_version(table_group_id) -> bool
    SELECT 1 FROM data_contracts WHERE table_group_id = ? LIMIT 1
```

All functions decorated with `@with_database_session`.

### ORM model update: `testgen/common/models/table_group.py`

Add two fields to the `TableGroup` SQLAlchemy model:
```python
contract_stale:          bool | None = Column(Boolean, default=False)
last_contract_save_date: datetime | None = Column(...)
```

Do **not** remove `contract_version` or `contract_status` — leave as deprecated columns.

**Files changed:**
- `testgen/commands/contract_versions.py` — new file
- `testgen/common/models/table_group.py` — add two fields

**Tests:** `tests/unit/commands/test_contract_versions.py` (all classes from design §13)

---

## Phase 3 — Staleness detection hooks

**Goal:** `contract_stale` is automatically set when the system changes after a save.

### New function: `mark_contract_stale(table_group_id)`

Add to `testgen/commands/contract_versions.py`:

```python
def mark_contract_stale(table_group_id: str) -> None:
    """Set contract_stale = TRUE if a saved contract exists for this table group."""
    # Only mark stale if there is at least one saved version — nothing to be stale against otherwise.
    UPDATE table_groups
    SET contract_stale = TRUE
    WHERE id = :tg_id
      AND last_contract_save_date IS NOT NULL
```

### Hook into profiling completion

In `testgen/commands/run_profiling.py`, after a profiling run completes successfully, call:
```python
mark_contract_stale(table_group_id)
```

### Hook into test definition changes

In `testgen/ui/views/test_suites.py` (and any command that inserts/updates/deletes test definitions), call `mark_contract_stale(table_group_id)` after the DB write.

Identify all call sites with:
```
grep -r "test_definitions" testgen/commands/ testgen/ui/views/ --include="*.py" -l
```

### Hook into suite scope changes

In `testgen/ui/views/test_suites.py`, wherever `include_in_contract` is toggled, call `mark_contract_stale(table_group_id)`.

**Files changed:**
- `testgen/commands/contract_versions.py` — add `mark_contract_stale`
- `testgen/commands/run_profiling.py` — add call after completion
- `testgen/ui/views/test_suites.py` — add calls on test definition and scope changes
- Any other command that mutates `test_definitions`

**Tests:** `tests/unit/commands/test_staleness_detection.py` (all classes from design §13)

---

## Phase 4 — Staleness diff computation

> **Status**: File `contract_staleness.py` exists with basic structure. SQL column bugs fixed (`status`→`result_status`, `test_definition_id_fk`→`test_definition_id`). Composite FK ref matching fixed with `_ref_matches()` helper. Full diff logic still needed.

**Goal:** When `contract_stale` is TRUE, compute a categorized diff so the banner can say exactly what changed.

### New file: `testgen/commands/contract_staleness.py`

```
compute_staleness_diff(table_group_id, saved_yaml) -> StaleDiff

@dataclass
class StaleDiff:
    schema_changes: list[dict]     # {"change": "added"|"removed"|"changed", "table": str, "column": str, "detail": str}
    quality_changes: list[dict]    # {"change": "added"|"removed"|"changed", "element": str, "test_type": str, "detail": str, "last_result": str|None}
    governance_changes: list[dict] # {"change": "changed", "table": str, "column": str, "field": str}
    suite_scope_changes: list[dict]# {"change": "added"|"removed", "suite_name": str}

    @property
    def is_empty(self) -> bool: ...

    def summary_parts(self) -> list[str]:
        # e.g. ["2 new columns", "1 test threshold changed"]
```

Logic:
1. Parse `saved_yaml` → snapshot dict
2. Query current `data_column_chars` for schema / governance state
3. Query current `test_definitions` (active, in-contract suites) for quality state
4. Query `test_suites.include_in_contract` for scope state
5. Diff each category against the snapshot's `schema`, `quality`, and `x-testgen.includedSuites` sections

**Files changed:**
- `testgen/commands/contract_staleness.py` — new file

**Tests:** `tests/unit/commands/test_staleness_diff.py` (all classes from design §13)

---

## Phase 5 — Pending edit model

**Goal:** Edit dialogs write to session state only. DB writes happen only on version save. This is the most invasive change to the existing view and needs the most care.

### Session state schema

Two keys work together and must never be cleared independently:

```python
pending_key = f"dc_pending:{table_group_id}"
# Pending edits — survives rerenders, cleared only on version save or explicit discard.
# Structure:
# {
#   "governance": [{"table": str, "col": str, "field": str, "value": any}, ...],
#   "tests":      [{"rule_id": str, "field": str, "value": any}, ...],
# }

yaml_key = f"dc_yaml:{table_group_id}"
# The in-memory YAML doc — patched in place as each edit is applied.
# This is the rendering source of truth. It must stay in sync with pending_key.
# Rule: every write to pending_key must also patch yaml_key in the same handler call.
# Never pop yaml_key while pending_key is non-empty — doing so reloads the saved
# snapshot from DB, discarding the pending overlay.
```

### YAML patch-on-edit pattern

Every edit dialog "Apply" handler must do both steps atomically (within the same Streamlit callback, before `safe_rerun()`):

```python
# 1. Parse the current in-memory YAML
doc = yaml.safe_load(st.session_state[yaml_key]) or {}

# 2. Patch the field in the doc
prop["classification"] = new_value   # example

# 3. Write the patched YAML back — this drives what the page renders
st.session_state[yaml_key] = yaml.dump(doc, ...)

# 4. Record the edit in pending_key — this drives the dirty button and save dialog
pending = st.session_state.setdefault(pending_key, {"governance": [], "tests": []})
# Replace any prior edit for this same field (second edit wins)
pending["governance"] = [
    e for e in pending["governance"]
    if not (e["table"] == table_name and e["col"] == col_name and e["field"] == field_name)
]
pending["governance"].append({"table": table_name, "col": col_name,
                               "field": field_name, "value": new_value})
st.session_state[pending_key] = pending
```

This pattern ensures the page always renders from the patched YAML, and the pending list is always consistent with it.

### Changes to `_claim_edit_dialog` (governance)

- Remove the `run_import_data_contract(..., dry_run=False)` call (line 1062)
- Remove the `_persist_governance_deletion` calls (lines 988, 1090)
- On "Apply": apply the YAML patch-on-edit pattern above
- On "Delete": same pattern — patch YAML to remove the field, add a deletion entry to pending

### Changes to `_edit_rule_dialog` (test claims)

- Remove the `run_import_data_contract(..., dry_run=False)` call (line 1197)
- On "Apply": patch the relevant quality rule in the in-memory YAML doc, append to `pending["tests"]`

### New dialog: `_save_version_dialog`

```python
@st.dialog("Save New Version", width="small")
def _save_version_dialog(table_group_id, pending_edits, current_version):
    # Show list of pending changes from pending_edits
    # Show label text input
    # On confirm — all steps in a single try/except, rolled back on failure:
    #   1. Apply governance pending edits → data_column_chars  (DB write)
    #   2. Apply test pending edits → test_definitions         (DB write)
    #   3. Build snapshot YAML by patching the current in-memory YAML
    #      with the confirmed pending edits.
    #      Do NOT call run_export_data_contract() here — a fresh export
    #      would pull in new anomalies/test results that happened after
    #      the user started editing, producing a snapshot that doesn't
    #      match what the user reviewed.
    #   4. save_contract_version(table_group_id, snapshot_yaml, label)
    #   5. Clear pending_key and pop yaml_key (next render loads new saved version)
    #   6. safe_rerun()
```

Step 3 is the key difference from a naive implementation: the snapshot is the current in-memory patched YAML, not a fresh DB export. This guarantees the saved snapshot is exactly what the user saw on screen.

### Dirty button in header

The "Save new version" button:
- Shows as subdued (secondary style) when `pending_key` is absent or empty
- Shows as primary + `●` dot when `pending_key` has entries
- `help=` tooltip lists the pending changes (e.g. "1 unsaved change — orders.customer_id: classification → restricted")

### Navigation guard

In `render()`, check `pending_key` before any navigation that would clear session state. If non-empty, show a confirmation dialog. If the user confirms leaving, pop both `pending_key` and `yaml_key`.

**Files changed:**
- `testgen/ui/views/data_contract.py` — rewrite `_claim_edit_dialog`, `_edit_rule_dialog`, add `_save_version_dialog`, add dirty button logic, add navigation guard

**Tests:** `tests/unit/ui/test_contract_pending_edits.py` (all classes from design §13)

---

## Phase 6 — Page load from saved snapshot

**Goal:** The page loads from `data_contracts`, not from a fresh export. This replaces `_capture_yaml`.

### Changes to `render()` in `DataContractPage`

Replace the current load path:
```python
# BEFORE
if yaml_key not in st.session_state:
    buf = io.StringIO()
    _capture_yaml(table_group_id, buf)
    st.session_state[yaml_key] = buf.getvalue()
```

With:
```python
# AFTER
if not has_any_version(table_group_id):
    _render_first_time_flow(table_group_id)
    return

requested_version = st.query_params.get("version")  # None = latest
version_record = load_contract_version(table_group_id, requested_version)
# version_record is {version, saved_at, label, contract_yaml}
st.session_state[yaml_key] = version_record["contract_yaml"]
st.session_state[version_key] = version_record
```

### Session state keys (updated)

```python
yaml_key    = f"dc_yaml:{table_group_id}"       # the YAML string
version_key = f"dc_version:{table_group_id}"    # {version, saved_at, label}
pending_key = f"dc_pending:{table_group_id}"    # pending edits
anomaly_key = f"dc_anomalies:{table_group_id}"  # live anomalies (unchanged)
filter_key  = f"dc_filter:{table_group_id}"     # active filter (unchanged)
```

### Refresh button

The `on_refresh` handler now:
1. If `pending_key` is non-empty: show confirmation dialog ("Leave unsaved changes?")
2. Pops `yaml_key` and `version_key` from session state (forces reload from DB)
3. Does **not** call `run_export_data_contract` — the next render picks up the saved snapshot

**Files changed:**
- `testgen/ui/views/data_contract.py` — rewrite `render()` load path, rewrite `on_refresh`
- `testgen/commands/contract_versions.py` — `has_any_version`, `load_contract_version` (already added in Phase 2)

---

## Phase 7 — First-time flow

**Goal:** When `has_any_version()` is False, show the prerequisites gate → preview → save as version 0.

### New function: `_render_first_time_flow(table_group_id)`

```
Step 1 — Prerequisites check
  - Query: last profiling run date for this table group
  - Query: count of non-monitor test suites with active tests
  - Query: % of columns with description or PII flag
  - Render the prerequisite checklist (✅/❌ with links)
  - If both required items are met: show [Generate Contract Preview →]

Step 2 — Preview (after button click, stored in session state)
  - Call run_export_data_contract() to build the live YAML
  - Render health dashboard + gap analysis from the preview doc
  - Show [← Back] and [Save as Version 0]

Step 3 — Save
  - [Save as Version 0] opens _save_version_dialog with empty pending edits
  - save_contract_version(table_group_id, preview_yaml, label)
  - Clears the first-time flow session state
  - safe_rerun() → render() now finds a saved version and shows normal view
```

**Session state for first-time flow:**
```python
preview_key = f"dc_preview:{table_group_id}"   # preview YAML, set after Generate click
```

**Files changed:**
- `testgen/ui/views/data_contract.py` — add `_render_first_time_flow`

**Tests:** `tests/unit/ui/test_contract_first_time_flow.py` (all classes from design §13)

---

## Phase 8 — Staleness banner and diff panel

**Goal:** When `contract_stale` is TRUE, show the banner with specific changes. "Review Changes" opens the diff panel. Save is only available inside the panel.

### Load staleness state in `render()`

After loading the version record:
```python
table_group = ...  # existing fetch
is_stale = bool(getattr(table_group, "contract_stale", False))
stale_diff = None
if is_stale:
    stale_diff = compute_staleness_diff(table_group_id, version_record["contract_yaml"])
    if stale_diff.is_empty:
        # False positive — clear the flag
        mark_contract_stale_false(table_group_id)
        is_stale = False
```

### Staleness banner rendering

```python
def _render_staleness_banner(version_record, stale_diff, table_group_id):
    if not stale_diff:
        return
    parts = stale_diff.summary_parts()
    st.warning(
        f"Contract version {version_record['version']} was saved on "
        f"{version_record['saved_at'].strftime('%b %d, %Y')}. "
        f"Since then: {', '.join(parts)}.",
        icon="⚠️"
    )
    col1, col2 = st.columns([1, 6])
    if col1.button("Review Changes"):
        _review_changes_panel(stale_diff, table_group_id, version_record)
    if col2.button("Dismiss"):
        st.session_state[f"dc_stale_dismissed:{table_group_id}"] = True
        safe_rerun()
```

### `_review_changes_panel` dialog

```python
@st.dialog("Changes Since Version N", width="large")
def _review_changes_panel(stale_diff, table_group_id, version_record):
    # Render categorized changes: schema / quality / governance / suite scope
    # Each quality change shows last_result if available
    # [Close] and [Save new version →] buttons
    # [Save new version →] calls _save_version_dialog(...)
```

**Files changed:**
- `testgen/ui/views/data_contract.py` — add `_render_staleness_banner`, `_review_changes_panel`
- `testgen/commands/contract_staleness.py` — `compute_staleness_diff` (Phase 4)

**Tests:** `tests/unit/ui/test_contract_staleness_ui.py` (all classes from design §13)

---

## Phase 9 — Version picker and historic view

**Goal:** The version indicator in the header is a dropdown. Selecting a past version renders a read-only view of that snapshot.

### Version picker in the header

In `render()`, after loading `version_record`:
```python
versions = list_contract_versions(table_group_id)
is_latest = (version_record["version"] == versions[0]["version"])
```

Render a selectbox in the header area showing `{version}  {date}  {label}`. On change, update `st.query_params["version"]` and `safe_rerun()`.

Limit display to the 20 most recent; add "Show all history →" link if more exist (links to a future history page).

### Historic version read-only mode

When `not is_latest`:
- Show a blue banner: "Viewing version N — saved {date}. This is read-only. [View Latest →]"
- Disable all edit chip buttons (pass `is_readonly=True` down the render chain)
- Disable the Refresh button and the dirty save button
- Hygiene card shows live anomalies + caption: "Anomalies are always current — not from this snapshot"
- "Download YAML" remains active

### Propagate `is_readonly` through render chain

Add `is_readonly: bool = False` parameter to:
- `_render_schema_claims`
- `_render_live_claims_row`
- `_render_health_dashboard`

When `is_readonly=True`, suppress all `st.button("✏️ Edit", ...)` renders and add tooltip on hover (via `disabled=True` + `help=...`).

**Files changed:**
- `testgen/ui/views/data_contract.py` — add version picker, historic banner, `is_readonly` propagation

**Tests:** `tests/unit/ui/test_contract_historic_view.py` (all classes from design §13)

---

## Phase 10 — Remove old lifecycle artifacts

**Goal:** Kill dead code that will confuse future maintainers and surface wrong UI state.

### In `data_contract.py`

- Remove `_STATUS_COLOR` dict (lines 33–39) — maps old lifecycle states
- Remove `meta["status"]` from `_build_contract_props` (line 1289) — sends `"draft"` to VanJS
- Remove the import of `ContractDiff` from `import_data_contract` in the event handler — the import path now only runs at version-save time via `_save_version_dialog`
- Remove `_render_upload_section` and the `on_import_contract` event handler — YAML upload is replaced by the version save flow

### In `import_data_contract.py`

- Remove the `contract_version` and `contract_status` fields from `ContractDiff.contract_updates` and from `apply_diff` — these columns are deprecated
- Remove the `compute_diff` branches that update those fields

### In `testgen/common/models/table_group.py`

- Mark `contract_version` and `contract_status` fields with a deprecation comment; do not remove the column definitions (the DB columns still exist)

### In `test_data_contract_export.py`

- Delete `Test_ValidStatuses` class
- Update `Test_RunExportDataContract` to remove assertions on `contract_status` in YAML

**Files changed:**
- `testgen/ui/views/data_contract.py`
- `testgen/commands/import_data_contract.py`
- `testgen/common/models/table_group.py`
- `tests/unit/commands/test_data_contract_export.py`

---

## Phase 11 — Frontend (VanJS) updates

**Goal:** Align the JS component with the new page model. Most logic is in Python; the frontend changes are additions, not rewrites.

### `data_contract.js` changes

| Change | What |
|---|---|
| Remove lifecycle status pill | The `status` prop (`"draft"` etc.) is no longer sent; remove the pill render |
| Version display | Show plain integer version + timestamp in the header, not the old `contract_version` string |
| Version picker | Render a `<select>` populated from `versions` prop; on change emit `VersionChanged` event |
| Staleness indicator | Read `is_stale` prop; show ⚠️ badge next to version in header |
| Pending edit indicator | Read `pending_count` prop; show dot on save button when > 0 |
| Historic read-only | Read `is_readonly` prop; disable all edit chip click handlers |
| Historic hygiene caption | When `is_readonly`, show caption on hygiene card |

### New props passed from Python to VanJS

```python
"versions":      list_contract_versions(table_group_id),   # [{version, saved_at, label}, ...]
"current_version": version_record["version"],
"is_latest":     is_latest,
"is_stale":      is_stale,
"pending_count": len(pending_edits.get("governance", []) + pending_edits.get("tests", [])),
"is_readonly":   not is_latest,
```

**Files changed:**
- `testgen/ui/components/frontend/js/pages/data_contract.js`

---

## Phase 12 — Tests

**Goal:** All new test files from the design are written and passing.

| File | Depends on phase |
|---|---|
| `tests/unit/commands/test_contract_versions.py` | Phase 2 |
| `tests/unit/commands/test_staleness_detection.py` | Phase 3 |
| `tests/unit/commands/test_staleness_diff.py` | Phase 4 |
| `tests/unit/ui/test_contract_pending_edits.py` | Phase 5 |
| `tests/unit/ui/test_contract_first_time_flow.py` | Phase 7 |
| `tests/unit/ui/test_contract_staleness_ui.py` | Phase 8 |
| `tests/unit/ui/test_contract_historic_view.py` | Phase 9 |

Run full test suite after each phase: `pytest -m unit`.

---

## Execution order and dependencies

```
Phase 1  DB migration
    └─► Phase 2  Contract version data layer
            ├─► Phase 3  Staleness detection hooks
            │       └─► Phase 4  Staleness diff computation
            ├─► Phase 5  Pending edit model          ◄── Phases 1+2 only
            ├─► Phase 6  Page load from snapshot     ◄── Phases 2+5
            │       └─► Phase 7  First-time flow
            ├─► Phase 8  Staleness banner+panel      ◄── Phases 3+4+6
            ├─► Phase 9  Version picker+historic     ◄── Phases 2+6
            ├─► Phase 10 Remove old artifacts        ◄── Phases 5+6 complete
            └─► Phase 11 Frontend updates            ◄── Phases 5+6+9
Phase 12 Tests (written alongside each phase)
```

Phases 5, 7, 8, 9, 10 can run in parallel once Phase 6 is done.  
Phase 11 can start once Phases 5, 6, and 9 are done.

---

## Files touched summary

### Already changed (pre-plan + coverage matrix redesign + code review)

| File | Change type |
|---|---|
| `testgen/template/dbupgrade/0180_incremental_upgrade.sql` | New — `include_in_contract` on `test_suites` |
| `testgen/template/dbupgrade/0181_incremental_upgrade.sql` | New — additional schema changes |
| `testgen/template/dbupgrade/0182_incremental_upgrade.sql` | New — additional schema changes |
| `testgen/template/dbupgrade/0183_incremental_upgrade.sql` | New — `is_monitor` on `test_suites` |
| `testgen/ui/views/data_contract.py` | New — full page implementation |
| `testgen/ui/components/frontend/js/pages/data_contract.js` | New — VanJS page (coverage matrix 5-tier, ClaimCountsBar, ts-name/ts-meta headers, table-level monitor rows) |
| `testgen/commands/export_data_contract.py` | New — ODCS YAML export + `_pii_flag_to_classification` |
| `testgen/commands/import_data_contract.py` | New — YAML import back to DB |
| `testgen/commands/contract_staleness.py` | New — staleness diff structure (partial) |
| `testgen/ui/views/test_suites.py` | Modify — link to data contract page |
| `testgen/ui/views/table_groups.py` | Modify — link to data contract page |
| `tests/unit/commands/test_data_contract_export.py` | New |
| `tests/unit/commands/test_data_contract_import.py` | New |
| `tests/unit/commands/test_staleness_diff.py` | New — `Test_GovernanceDiff` class |
| `tests/unit/ui/test_data_contract_page.py` | New — `Test_ClaimCountConsistency` (8 tests) |

### Still needed (phases 1–11)

| File | Change type |
|---|---|
| `testgen/template/dbupgrade/0184_incremental_upgrade.sql` | New — `data_contracts` table + staleness columns |
| `testgen/commands/contract_versions.py` | New |
| `testgen/commands/run_profiling.py` | Modify — add staleness hook |
| `testgen/common/models/table_group.py` | Modify — add `contract_stale`, `last_contract_save_date` |
| `testgen/ui/views/data_contract.py` | Major additions — pending edit model, version load, first-time flow, staleness banner |
| `testgen/ui/components/frontend/js/pages/data_contract.js` | Modify — remove status pill, add version picker |
| `tests/unit/commands/test_contract_versions.py` | New |
| `tests/unit/commands/test_staleness_detection.py` | New |
| `tests/unit/ui/test_contract_pending_edits.py` | New |
| `tests/unit/ui/test_contract_first_time_flow.py` | New |
| `tests/unit/ui/test_contract_staleness_ui.py` | New |
| `tests/unit/ui/test_contract_historic_view.py` | New |
