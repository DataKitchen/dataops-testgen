# Contract Snapshot Suite — Design Spec

## Overview

When a contract version is saved, a new **snapshot test suite** is created that captures the exact set of tests in scope for that contract version. Three saved contract versions produce three test suites. Each snapshot suite is visible in the test suites UI but **locked** — tests can only be added, edited, or deleted via the Data Contract UI. The test suites UI shows a clear message directing users there.

---

## User-Facing Behavior

| Action | Result |
| :--- | :--- |
| Save contract v0 (first save) | Warning shown → user confirms → creates `Contract v0 — {table_group_name}` |
| Save contract v1 | Warning shown → user confirms → creates `Contract v1 — {table_group_name}` |
| Regenerate & Save as v2 | Warning shown → user confirms → creates `Contract v2 — {table_group_name}` |
| Open contract v0 in UI | Shows tests from `Contract v0` snapshot suite |
| Open contract v1 in UI | Shows tests from `Contract v1` snapshot suite |
| Add/edit/delete test in contract UI | Writes directly to the snapshot suite's test definitions |
| Open snapshot suite in test suites UI | Visible, executable, but edit/add/delete actions suppressed — message shown: "Managed by Data Contract UI" |
| Open source suite in test suites UI | Normal — shows "In contract" indicator if feeding an active contract |

---

## Warning UI — Before Creating a Snapshot Suite

Both `_save_version_dialog` and `_regenerate_dialog` show an `st.info` message inside the dialog before the save button:

```
A new test suite will be created:
  [Contract v{N}] {table_group_name}

It will contain a copy of all tests currently in scope for this contract.
Tests in this suite can only be managed from the Data Contract UI.
```

`table_group_name` resolved via `TableGroup.get_minimal(table_group_id).table_groups_name`.

---

## Database Changes — Migration `0185`

### `test_suites` — new column

```sql
ALTER TABLE {schema}.test_suites
  ADD COLUMN IF NOT EXISTS is_contract_snapshot BOOLEAN NOT NULL DEFAULT FALSE;
```

### `data_contracts` — new column

```sql
ALTER TABLE {schema}.data_contracts
  ADD COLUMN IF NOT EXISTS snapshot_suite_id UUID
    REFERENCES {schema}.test_suites(id) ON DELETE SET NULL;
```

Links each contract version record to its snapshot suite.

### `test_definitions` — new column

```sql
ALTER TABLE {schema}.test_definitions
  ADD COLUMN IF NOT EXISTS source_test_definition_id UUID
    REFERENCES {schema}.test_definitions(id) ON DELETE SET NULL;
```

Links each snapshot test copy back to the source test definition it was copied from.

---

## New Command — `testgen/commands/contract_snapshot_suite.py`

```python
def create_contract_snapshot_suite(table_group_id: str, version: int) -> UUID:
    """
    Create a snapshot test suite for the given contract version.
    Copies all active test definitions from suites where:
      - table_groups_id = table_group_id
      - include_in_contract = TRUE
      - is_monitor IS NOT TRUE
      - is_contract_snapshot IS NOT TRUE

    Updates data_contracts.snapshot_suite_id for the matching version row.
    Returns the new suite UUID.
    """
```

### Steps

1. Look up `table_group_name` from `table_groups`
2. Create new `TestSuite` row:
   - `test_suite = f"Contract v{version} — {table_group_name}"`
   - `is_contract_snapshot = True`
   - `include_in_contract = True` — **must be True** so existing queries that filter on `include_in_contract` continue to work; the `is_contract_snapshot` flag is the sole marker that identifies this as a snapshot (see Query Exclusions below)
   - `table_groups_id`, `connection_id`, `project_code`, `severity` copied from first source suite
3. Query `data_contracts WHERE table_group_id=X AND version=N` to get the contract record ID
4. Bulk-copy all test definitions from source suites using a single raw SQL `INSERT INTO … SELECT` statement (not `TestDefinition.copy()` — see Critical Fix 1 below):

```sql
INSERT INTO {schema}.test_definitions (
    id, test_suite_id, source_test_definition_id,
    -- all other columns verbatim...
)
SELECT
    gen_random_uuid(),        -- new id for each copy
    :new_suite_id,            -- redirect to snapshot suite
    td.id,                    -- source_test_definition_id = original row id
    -- all other columns verbatim from td...
FROM {schema}.test_definitions td
JOIN {schema}.test_suites ts ON ts.id = td.test_suite_id
WHERE ts.table_groups_id = :tg_id
  AND ts.include_in_contract = TRUE
  AND ts.is_monitor IS NOT TRUE
  AND ts.is_contract_snapshot IS NOT TRUE;
```

5. `UPDATE data_contracts SET snapshot_suite_id = :new_suite_id WHERE id = :record_id`
6. Return new suite UUID

### Critical Fix 1 — Why raw SQL instead of `TestDefinition.copy()`

`TestDefinition.copy()` builds its column list from `cls.__table__.columns` excluding only `id`. It copies column values verbatim, so `source_test_definition_id` would be copied as `NULL` (its value in source suite rows) rather than set to the source row's `id`. Using a raw `INSERT INTO … SELECT` with explicit column mapping is the only way to correctly populate `source_test_definition_id = td.id`.

### Critical Fix 2 — Query exclusions

All queries in `testgen/ui/queries/data_contract_queries.py` that filter on `include_in_contract` must also exclude snapshot suites to prevent them appearing in the suite scope panel or inflating health dashboard counts:

- `_fetch_suite_scope` — add `AND ts.is_contract_snapshot IS NOT TRUE`
- `_fetch_test_statuses` — add `AND ts.is_contract_snapshot IS NOT TRUE`
- `_fetch_last_run_dates` — add `AND ts.is_contract_snapshot IS NOT TRUE`

These three queries drive the contract health grid and suite scope picker. Without this filter, snapshot suites would appear as legitimate "included" source suites in the contract UI.

### Critical Fix 3 — Atomicity

`save_contract_version` commits via `execute_db_queries` before `create_contract_snapshot_suite` runs. If snapshot creation fails after that point, the `data_contracts` row exists with `snapshot_suite_id = NULL` and there is no rollback.

Resolution: `create_contract_snapshot_suite` runs both the suite creation and the `UPDATE data_contracts SET snapshot_suite_id` inside a **single `execute_db_queries` call** (both statements in the same array). If either fails, neither commits. The version record (`save_contract_version`) is a separate prior commit — that is acceptable, since a missing `snapshot_suite_id` is recoverable (show the static fallback count in the UI) whereas a half-written suite is not.

---

## Hook Points

Both dialogs in `testgen/ui/views/dialogs/data_contract_dialogs.py`:

```python
# _save_version_dialog — after save_contract_version(...)
version = save_contract_version(table_group_id, current_yaml, label or None)
create_contract_snapshot_suite(table_group_id, version)

# _regenerate_dialog — after save_contract_version(...)
new_version = save_contract_version(table_group_id, fresh_yaml, label or None)
create_contract_snapshot_suite(table_group_id, new_version)
```

---

## Contract UI Changes

### Test count — becomes a link

Where the test count chip is shown for the current version, make it a link to:
`/test-definitions?test_suite_id={snapshot_suite_id}`

Only when a snapshot suite exists. Falls back to static count for pre-feature versions.

### Add test button

An **"Add test"** button is placed in the `col-header` div of each `ColumnRow` in `data_contract.js`, immediately after `GovernanceButton`. Same style and pattern as the governance button.

```
[col name]  [col type]  [PK]  [Add / Edit governance]  [Add test]
```

Only rendered when `snapshot_suite_id` is set on the current version props and `is_latest` is true.

**JS:** emits `AddTestClicked` with `{ tableName, colName }`.

**Python (`on_add_test` handler in `data_contract.py`):** fetches `TableGroupMinimal.get(table_group_id)` and `TestSuite.get(snapshot_suite_id)` (both cached in session state under `dc_snapshot_suite:{table_group_id}` to avoid repeated DB calls), then calls the existing `add_test_dialog(table_group, snapshot_suite, table_name, col_name)`. No new dialog needed.

### Edit existing test

**Current behavior:** clicking a test chip → `on_term_detail` → `_test_term_dialog` → "Edit test" button navigates away to the test definitions page.

**With snapshot suite:** in `on_term_detail`, when `source == "test"` **and** `snapshot_suite_id` exists for the current version, call `_edit_rule_dialog(rule, table_group_id, yaml_key)` directly instead of `_test_term_dialog`. The user stays in the contract UI and edits the snapshot suite's test definition in place.

**Without snapshot suite** (pre-feature contracts or historic versions): existing behavior unchanged — `_test_term_dialog` opens with the navigate-out "Edit test" button.

### Delete test

Existing multi-select bulk delete already works. For single-chip delete, the existing "Delete term from contract" button in `_test_term_dialog` remains for non-snapshot contracts. For snapshot-backed contracts, the same button deletes the test definition row from the snapshot suite directly (in addition to patching the YAML).

---

## Test Suites UI Changes

In `testgen/ui/views/test_suites.py`:

### Snapshot suites — locked

When `is_contract_snapshot=True`, suppress:
- Edit suite button
- Delete suite button
- Add test button
- Edit/delete test definition actions

Show instead:
- A **"Contract snapshot"** badge on the suite row
- An info banner at the top of the suite's test definitions view: _"This test suite is managed by the Data Contract UI. To add, edit, or remove tests, open the Data Contract for this table group."_ with a link to the contract page.

The suite remains **executable** (run tests, view results) — only test management actions are suppressed.

### Source suites — indicator only

For suites with `include_in_contract=True` where a saved contract exists for the table group, show a small **"In contract"** chip on the suite row. No functional changes.

---

## Staleness Diff — Term Differences Tab

The staleness diff (`compute_staleness_diff` in `testgen/commands/contract_staleness.py`) currently computes four change categories:

| Category | With snapshot suite |
| --- | --- |
| `schema_changes` | Still computed — DDL changes happen outside the contract |
| `quality_changes` | **Suppressed** — tests are locked to the snapshot suite and only changeable via contract UI, so they are always in sync with the YAML |
| `governance_changes` | Still computed — governance metadata is edited independently |
| `suite_scope_changes` | Still computed — source suite scope can still change |

### Implementation

`compute_staleness_diff` receives `table_group_id` and `contract_yaml`. Add a check: if the current contract version has a `snapshot_suite_id` (i.e. it is a snapshot-backed contract), skip the quality diff step and return an empty `quality_changes` list.

```python
# In compute_staleness_diff — after loading the contract version record:
if version_record.get("snapshot_suite_id"):
    quality_changes = []  # tests are locked to the snapshot suite — never stale
else:
    quality_changes = _compute_quality_changes(...)  # existing logic
```

The `_review_changes_panel` dialog and `StaleDiff.summary_parts()` require no changes — they already handle empty lists gracefully.

---

## What Does NOT Change

- Source test suites — untouched, fully editable
- YAML export logic — unchanged
- Contract YAML — frozen at save time; post-save edits to the snapshot suite via contract UI do not retroactively change the saved YAML (they apply to a future save)
- All existing test editing dialogs — reused as-is
- `StaleDiff` dataclass and `_review_changes_panel` — no changes needed; empty `quality_changes` already renders correctly

---

## Open Questions

1. ~~**Naming collision**~~ — resolved. Suite name format is `[Contract v{N}] {table_group_name}`. The `[Contract vN]` bracket prefix makes snapshot suites visually distinct from any user-created suite. `is_contract_snapshot` remains the authoritative marker.

2. ~~**Performance**~~ — resolved. Use `INSERT INTO … SELECT` for bulk copy.

3. ~~**Historic versions**~~ — resolved. Historic read-only view shows the snapshot suite test count as a clickable link to the test definitions page for that version's suite. Add/Edit/Delete controls are suppressed. Useful for auditing exact test coverage at a past version.
