# Contract Snapshot Suite — Design Spec

## Overview

When a contract version is saved, a new **snapshot test suite** is created that captures the exact set of tests in scope for that contract version. Three saved contract versions produce three test suites. Each snapshot suite is visible in the test suites UI but **locked** — tests can only be added, edited, or deleted via the Data Contract UI. The test suites UI shows a clear message directing users there.

---

## User-Facing Behavior

| Action | Result |
| :--- | :--- |
| Save contract v0 (first save) | Warning shown → user confirms → creates `[Contract v0] {table_group_name}` |
| Save contract v1 | Warning shown → user confirms → creates `[Contract v1] {table_group_name}` |
| Regenerate & Save as v2 | Warning shown → user confirms → creates `[Contract v2] {table_group_name}` |
| Open contract v0 in UI | Shows tests from `[Contract v0]` snapshot suite |
| Open contract v1 in UI | Shows tests from `[Contract v1]` snapshot suite |
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

**Edge case — no in-scope tests:** If no source suites have `include_in_contract=True` and active test definitions, `create_contract_snapshot_suite` raises a descriptive exception and the save is aborted. The dialog shows an error: "No in-scope tests found. Add tests to at least one contract suite before saving."

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
  ADD COLUMN IF NOT EXISTS source_test_definition_id UUID;
```

Links each snapshot test copy back to the source test definition it was copied from. Intentionally no FK constraint — the value must survive source TD deletion so that YAML import sync can find and remove the corresponding snapshot TD after `apply_import_diff` commits.

---

## Prerequisites — Existing Functions That Must Be Updated

### `load_contract_version` (`testgen/commands/contract_versions.py`)

Currently SELECTs only `version, saved_at, label, contract_yaml`. Must be updated to also SELECT `snapshot_suite_id` so that `version_record.get("snapshot_suite_id")` is populated at all call sites (staleness diff bypass, `on_term_detail` routing, contract UI test count link).

### `compute_staleness_diff` signature (`testgen/commands/contract_staleness.py`)

Add `snapshot_suite_id: str | None = None` parameter. The call site in `data_contract.py` (line 452) already has `version_record` in scope — pass `version_record.get("snapshot_suite_id")` there. This avoids an extra DB query inside `compute_staleness_diff`.

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
    Raises ValueError if no in-scope test definitions exist.
    """
```

### Steps

1. Look up `table_group_name` from `table_groups`
2. Check source test definitions exist — if none, raise `ValueError("No in-scope tests found")`
3. Execute all of the following as a **single `execute_db_queries` call** (both INSERT and UPDATE commit together or not at all):

   **Statement 1** — INSERT new `test_suites` row via raw SQL:
   - `test_suite = f"[Contract v{version}] {table_group_name}"`
   - `is_contract_snapshot = TRUE`
   - `include_in_contract = TRUE` — must be True; `is_contract_snapshot` is the sole marker identifying it as a snapshot
   - `connection_id`, `project_code`, `severity` copied from first source suite

   **Statement 2** — Bulk-copy test definitions:

```sql
INSERT INTO {schema}.test_definitions (
    id, test_suite_id, source_test_definition_id,
    -- all other columns verbatim from td...
)
SELECT
    gen_random_uuid(),
    :new_suite_id,
    td.id,                    -- source_test_definition_id = original row id
    -- all other columns verbatim...
FROM {schema}.test_definitions td
JOIN {schema}.test_suites ts ON ts.id = td.test_suite_id
WHERE ts.table_groups_id = :tg_id
  AND ts.include_in_contract = TRUE
  AND COALESCE(ts.is_monitor, FALSE) = FALSE
  AND COALESCE(ts.is_contract_snapshot, FALSE) = FALSE;
```

   **Statement 3** — Link suite to contract version:

```sql
UPDATE {schema}.data_contracts
SET snapshot_suite_id = :new_suite_id
WHERE table_groups_id = :tg_id AND version = :version;
```

4. Return new suite UUID

### Why raw SQL (not `TestDefinition.copy()`)

`TestDefinition.copy()` copies `source_test_definition_id` verbatim from source rows (which is `NULL`). The raw `INSERT INTO … SELECT` is the only way to set `source_test_definition_id = td.id` correctly.

### Atomicity

All three statements run in a single `execute_db_queries` call. The prior `save_contract_version` commit is a separate transaction — a missing `snapshot_suite_id` is recoverable (UI falls back to static count) whereas a half-written suite is not.

---

## Contract UI — Reading Tests from the Snapshot Suite

When `version_record.get("snapshot_suite_id")` is non-null, the contract UI's term panel loads test definitions directly from the snapshot suite rather than from source suites. This requires a conditional branch in the queries that back the term detail panel:

- **With snapshot:** `WHERE td.test_suite_id = :snapshot_suite_id`
- **Without snapshot** (pre-feature or `is_latest=False`): existing behavior — join across source suites where `ts.include_in_contract = TRUE`

`_fetch_test_statuses` is the primary query affected. The snapshot suite's test definitions carry their own `last_run_status` and `last_run_date` from execution, so no source-suite join is needed for snapshot-backed versions.

The health grid columns (one column per source suite) are unaffected — they continue to show source suite execution status and always exclude snapshot suites via `is_contract_snapshot IS NOT TRUE`.

---

## Query Exclusions — `testgen/ui/queries/data_contract_queries.py`

Four queries must add `AND ts.is_contract_snapshot IS NOT TRUE` to prevent snapshot suites appearing as source suites in the contract health grid, scope picker, or staleness diff:

- `_fetch_suite_scope`
- `_fetch_test_statuses`
- `_fetch_last_run_dates`
- `compute_staleness_diff` suite scope query (in `testgen/commands/contract_staleness.py`) — snapshot suite names like `[Contract v0] orders` would otherwise appear as newly-added suites in the suite scope diff

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

`AddTestClicked` must be registered in the `event_handlers` dict in `data_contract.py` alongside the existing handlers (e.g. `TermDetailClicked`, `GovernanceEditClicked`). The `testgen_component.py` `AvailableEvents` list must also include `AddTestClicked`.

---

## Contract UI Changes

### Test count — becomes a link

Where the test count chip is shown for the current version, make it a link to:
`/test-definitions?test_suite_id={snapshot_suite_id}`

Only when `version_record.get("snapshot_suite_id")` is non-null. Falls back to static count for pre-feature versions.

### Add test button

An **"Add test"** button is placed in the `col-header` div of each `ColumnRow` in `data_contract.js`, immediately after `GovernanceButton`. Same style and pattern as the governance button.

```
[col name]  [col type]  [PK]  [Add / Edit governance]  [Add test]
```

Only rendered when `snapshot_suite_id` is present in the current version props and `is_latest` is true.

**JS:** emits `AddTestClicked` with `{ tableName, colName }`.

**Python (`on_add_test` handler in `data_contract.py`):** fetches `TableGroupMinimal.get(table_group_id)` and `TestSuite.get(snapshot_suite_id)` on demand, then calls the existing `add_test_dialog(table_group, snapshot_suite, table_name, col_name)`. No new dialog needed.

### Edit existing test

**With snapshot suite:** in `on_term_detail`, when `source == "test"` **and** `version_record.get("snapshot_suite_id")` is non-null, call `_edit_rule_dialog(rule, table_group_id, yaml_key)` directly. The user stays in the contract UI.

**Without snapshot suite** (pre-feature contracts or `is_latest=False`): existing behavior — `_test_term_dialog` with navigate-out "Edit test" button. Note: `is_latest=False` always routes to `_term_read_dialog` regardless of snapshot.

### Delete test

For snapshot-backed contracts, the "Delete term from contract" button in `_test_term_dialog` also deletes the test definition row from the snapshot suite directly (in addition to patching the YAML):

```sql
DELETE FROM {schema}.test_definitions
WHERE source_test_definition_id = :source_td_id
  AND test_suite_id = :snapshot_suite_id;
```

The `source_td_id` is the `id` field stored in the YAML term (which equals the source test definition's UUID). Existing multi-select bulk delete works unchanged.

---

## Staleness Diff — Term Differences Tab

The staleness diff (`compute_staleness_diff`) currently computes four change categories:

| Category | With snapshot suite |
| --- | --- |
| `schema_changes` | Still computed — DDL changes happen outside the contract |
| `quality_changes` | **Suppressed** — tests are locked to the snapshot suite; always in sync |
| `governance_changes` | Still computed — governance metadata is edited independently |
| `suite_scope_changes` | Still computed — source suite scope can still change |

### Implementation

```python
# compute_staleness_diff signature update:
def compute_staleness_diff(
    table_group_id: str,
    saved_yaml: str,
    snapshot_suite_id: str | None = None,   # NEW — passed from call site
) -> StaleDiff:
    ...
    if snapshot_suite_id:
        quality_changes = []  # tests locked to snapshot suite — never stale
    else:
        quality_changes = _compute_quality_changes(...)
```

Call site in `data_contract.py` (line ~452):
```python
stale_diff = compute_staleness_diff(
    table_group_id,
    version_record["contract_yaml"],
    snapshot_suite_id=version_record.get("snapshot_suite_id"),  # NEW
)
```

### Description text in the Term Differences tab

The Term Differences tab must display an explanatory paragraph at the top of the `_review_changes_panel` dialog so users understand what is and isn't shown:

> **What this shows:** Changes detected between your saved contract and the current state of your data environment — new or removed columns, governance metadata updates, and changes to which test suites are in scope. Quality rule differences are not shown here because tests are managed directly in the contract UI and are always up to date.

This text is always shown at the top of the panel, whether or not there are any changes. It is rendered as `st.caption(...)` or a styled `st.markdown(...)` block above the change list.

---

## Test Suites UI Changes

`is_contract_snapshot` must be included in the `TestSuiteSummary` dataclass and the `select_summary` SQL query so the frontend can receive it as a prop and conditionally suppress edit/delete/add-test actions and show the "Contract snapshot" badge.

### Snapshot suites — locked

When `is_contract_snapshot=True` (received as a prop), the frontend suppresses:
- Edit suite button
- Delete suite button
- Add test button
- Edit/delete test definition actions

Shows instead:
- A **"Contract snapshot"** badge on the suite row
- An info banner: _"This test suite is managed by the Data Contract UI. To add, edit, or remove tests, open the Data Contract for this table group."_ with a link to the contract page.

The suite remains **executable** — only test management actions are suppressed.

### Source suites — indicator only

For suites with `include_in_contract=True` where a saved contract exists, show a small **"In contract"** chip on the suite row. No functional changes.

---

## YAML Import → Snapshot Suite Sync

When a user uploads a modified YAML via the Import/Upload tab, `run_import_contract` calls `apply_import_diff` which creates, updates, or deletes test definitions in source suites. If the current contract version has a `snapshot_suite_id`, those same mutations must be mirrored into the snapshot suite.

### When sync applies

Sync applies **only when all three conditions are true**:

1. The current contract version record has a non-null `snapshot_suite_id`
2. `is_latest=True` (only the current version can be uploaded to)
3. The import diff contains quality rule changes (`created`, `updated`, or `deleted` test definitions)

### Three mutation cases

**Created rules** (rules without `id` in uploaded YAML — new tests):

After `apply_import_diff` creates new test definition rows in source suites, copy each new row into the snapshot suite exactly as `create_contract_snapshot_suite` does — one INSERT per new definition with `source_test_definition_id = new_source_td.id` and `test_suite_id = snapshot_suite_id`.

**Updated rules** (rules with `id` in uploaded YAML — edits to existing tests):

After `apply_import_diff` updates a source test definition row, find the corresponding snapshot row via `source_test_definition_id = updated_source_td.id` and apply the same field updates to that snapshot row.

**Deleted rules** (rules removed from uploaded YAML):

After `apply_import_diff` deletes a source test definition row, delete the corresponding snapshot row where `source_test_definition_id = deleted_source_td.id AND test_suite_id = snapshot_suite_id`.

### Implementation location

Add a `sync_import_to_snapshot_suite` function in `testgen/commands/contract_snapshot_suite.py`:

```python
def sync_import_to_snapshot_suite(
    snapshot_suite_id: str,
    created_td_ids: list[str],   # IDs of newly-created source test definitions
    updated_td_ids: list[str],   # IDs of updated source test definitions
    deleted_td_ids: list[str],   # IDs of deleted source test definitions
) -> None:
    """
    Mirror YAML import mutations into the snapshot suite.
    Called after apply_import_diff when snapshot_suite_id is non-null.
    All three operations run as a single execute_db_queries call.
    """
```

The call site is in `apply_import_diff` (or its caller in `data_contract.py`) after the source-suite mutations commit, passing `version_record.get("snapshot_suite_id")`.

### Empty-list no-op

If all three ID lists (`created_td_ids`, `updated_td_ids`, `deleted_td_ids`) are empty, `sync_import_to_snapshot_suite` returns immediately without calling `execute_db_queries`. No DB round-trip occurs.

### Atomicity note

The source-suite mutations and snapshot-suite sync are **separate transactions** — same reasoning as `save_contract_version` + `create_contract_snapshot_suite`. A failed sync is recoverable; the next YAML re-upload or contract re-save will bring the snapshot back into alignment.

### Known limitation — source TD deleted outside contract UI

If a source test definition is deleted directly (e.g., via the test definitions UI), the snapshot TD is **not removed** — `source_test_definition_id` retains the deleted source UUID (no FK, no SET NULL). Since `quality_changes` are suppressed for snapshot-backed contracts, the staleness diff will not flag this. The snapshot suite becomes silently inconsistent until the user regenerates and saves a new contract version.

This is a known limitation. Users should not delete source test definitions directly when a snapshot-backed contract exists. A future improvement could add a guard in the test definitions UI that warns when the TD is referenced by a snapshot suite.

---

## Delete Contract Version

A user can delete any saved contract version from the version history panel in the contract UI. Deleting a version also deletes its paired snapshot test suite and all test definitions in that suite.

### UI

The version history list (rendered via `list_contract_versions`) gains a **trash icon button** on each row. The button fires a `DeleteVersionClicked` event with `{ version: N }`.

Constraints on the button:
- The **only remaining version** — button is disabled (tooltip: "Cannot delete the only saved version").
- The **currently viewed version** if it is not the latest — button is enabled; after deletion the UI redirects to the latest version.
- The **latest version** — button is enabled with a stronger warning (see below).

### Warning dialog — `_delete_version_dialog`

```
Delete contract v{N}?

This will permanently delete:
  • Contract version v{N} ({label or "no label"}, saved {saved_at})
  • Test suite "[Contract v{N}] {table_group_name}" and all {count} tests in it

This action cannot be undone.
```

If the version has no snapshot suite (pre-feature contract), the suite line is omitted from the message.

**Two-step confirmation — always required:**

Below the message, a text input prompts:

```
Type DELETE to confirm
```

The confirm button remains disabled until the input exactly matches the string `DELETE` (case-sensitive). This applies to every version deletion, not just the latest.

If the version being deleted is the current latest, an additional `st.warning` appears above the input:

```
This is the most recent saved version. After deletion, v{N-1} will become the active contract.
```

**Fetching test count for the dialog:** When the dialog opens, the handler fetches `snapshot_suite_id` from `data_contracts` for the target version and executes `SELECT COUNT(*) FROM test_definitions WHERE test_suite_id = :snapshot_suite_id`. This is a lightweight read done at dialog-open time, not passed through the event payload. `list_contract_versions` does not need to return `snapshot_suite_id` or counts.

### New command — `delete_contract_version`

```python
def delete_contract_version(table_group_id: str, version: int) -> None:
    """
    Delete a contract version and its paired snapshot suite (if any).
    Raises ValueError if this is the only version for the table group.
    All three deletions run as a single execute_db_queries call.
    """
```

**Steps:**

1. Check that more than one version exists for `table_group_id` — if only one, raise `ValueError("Cannot delete the only saved version")`.
2. Fetch `snapshot_suite_id` from `data_contracts` for `(table_group_id, version)`.
3. Execute as a **single `execute_db_queries` call**:

   **Statement 1** — Delete test results for the snapshot suite (no-op if `snapshot_suite_id` is NULL):
   ```sql
   DELETE FROM {schema}.test_results
   WHERE test_suite_id = :snapshot_suite_id;
   ```

   **Statement 2** — Delete test definitions in the snapshot suite (no-op if NULL):
   ```sql
   DELETE FROM {schema}.test_definitions
   WHERE test_suite_id = :snapshot_suite_id;
   ```

   **Statement 3** — Delete the snapshot test suite (no-op if NULL):
   ```sql
   DELETE FROM {schema}.test_suites
   WHERE id = :snapshot_suite_id;
   ```

   **Statement 4** — Delete the contract version row:
   ```sql
   DELETE FROM {schema}.data_contracts
   WHERE table_groups_id = :tg_id AND version = :version;
   ```

   Statements 1–3 are skipped (not included) when `snapshot_suite_id` is NULL.

### Hook point

`DeleteVersionClicked` must be registered in `event_handlers` in `data_contract.py` and in `AvailableEvents` in `testgen_component.py`.

```python
# on_delete_version handler in data_contract.py
def on_delete_version(payload):
    version = payload["version"]
    # open _delete_version_dialog(table_group_id, version)
```

After successful deletion, if the deleted version was the currently viewed version (or the latest), rerun with `version` query param cleared so the UI loads the new latest version.

### User-facing behavior additions

| Action | Result |
| :--- | :--- |
| Click trash on v1 (not latest, not only) | Warning dialog → confirm → deletes version + snapshot suite |
| Click trash on latest version | Warning dialog with extra caution note → confirm → deletes |
| Click trash on only version | Button disabled |
| Delete pre-feature version (no snapshot) | Warning dialog (no suite line) → confirm → deletes version row only |

---

## What Does NOT Change

- Source test suites — untouched, fully editable
- YAML export logic — unchanged
- Contract YAML — frozen at save time; post-save edits to the snapshot suite via contract UI apply to a future save
- All existing test editing dialogs — reused as-is
- `StaleDiff` dataclass and `_review_changes_panel` structure — `quality_changes=[]` already renders correctly

---

## Test Coverage Plan

### `tests/unit/commands/test_contract_snapshot_suite.py`

**`create_contract_snapshot_suite`:**
1. Suite name format — `[Contract v2] My Group`
2. `is_contract_snapshot=True` in suite INSERT
3. `include_in_contract=True` in suite INSERT
4. `source_test_definition_id = td.id` in bulk copy SQL
5. `data_contracts.snapshot_suite_id` updated in same execute call
6. Monitor suites excluded from bulk copy (`is_monitor IS NOT TRUE`)
7. Existing snapshot suites excluded from bulk copy (`is_contract_snapshot IS NOT TRUE`)
8. `include_in_contract=FALSE` suites excluded from bulk copy
9. Single `execute_db_queries` call containing all three statements
10. Raises `ValueError` when no in-scope test definitions exist

**`sync_import_to_snapshot_suite`:**
11. Created IDs → INSERT into snapshot suite with `source_test_definition_id = created_td.id`
12. Updated IDs → UPDATE snapshot row where `source_test_definition_id = updated_td.id`
13. Deleted IDs → DELETE snapshot row where `source_test_definition_id = deleted_td.id`
14. Empty lists for all three → no DB calls made
15. `snapshot_suite_id=None` → no-op (skipped at call site)
16. Mixed ops (create + update + delete) run in a single `execute_db_queries` call

### `tests/unit/commands/test_staleness_diff_snapshot.py`
1. `quality_changes=[]` when `snapshot_suite_id` is non-null
2. `quality_changes` computed normally when `snapshot_suite_id=None`
3. `schema_changes` still computed when `snapshot_suite_id` is set
4. `suite_scope_changes` still computed when `snapshot_suite_id` is set
5. Suite scope query excludes snapshot suites

### `tests/unit/ui/test_contract_query_exclusions.py`
1. `_fetch_suite_scope` SQL contains `is_contract_snapshot IS NOT TRUE`
2. `_fetch_test_statuses` SQL contains `is_contract_snapshot IS NOT TRUE`
3. `_fetch_last_run_dates` SQL contains `is_contract_snapshot IS NOT TRUE`
4. Normal suites still returned by each query

### `tests/unit/ui/test_contract_on_term_detail_snapshot.py`
1. `source="test"` + snapshot → routes to `_edit_rule_dialog`
2. `source="test"` + no snapshot → routes to `_test_term_dialog`
3. `is_latest=False` + snapshot → routes to `_term_read_dialog`
4. `source="monitor"` + snapshot → routes to `_monitor_term_dialog` (unchanged)
5. `source="governance"` + snapshot → routes to `_term_edit_dialog` (unchanged)

### `tests/unit/ui/test_contract_dialog_warnings.py`
1. Save dialog `st.info` contains `[Contract v{N}]` suite name
2. Regenerate dialog `st.info` contains suite name
3. Save dialog calls `create_contract_snapshot_suite(tg_id, version)` after save
4. Regenerate dialog calls `create_contract_snapshot_suite(tg_id, version)` after save

### `tests/unit/commands/test_delete_contract_version.py`
1. `ValueError` raised when only one version exists
2. All three DELETE statements in a single `execute_db_queries` call when `snapshot_suite_id` is present
3. Only one DELETE statement (contract row) when `snapshot_suite_id` is NULL (pre-feature version)
4. Correct `tg_id` and `version` bound in the contract DELETE
5. `snapshot_suite_id` bound correctly in test_definitions and test_suites DELETEs

### What requires manual / integration testing
- `INSERT INTO … SELECT` SQL correctly copies all columns without nullifying `source_test_definition_id`
- DB atomicity under failure conditions
- JS `AddTestClicked` event payload correctness
- Test count chip renders as a link and navigates correctly
- Locked suite UI (frontend JS suppression of edit/delete buttons)
- "In contract" chip on source suite rows
- Migration 0185 on a live database with existing rows
- Delete version: trash button disabled when only one version exists
- Delete version: redirect to latest after deleting the currently viewed version
- Delete version: snapshot suite and all test definitions are fully removed from DB
- Delete version: pre-feature version (no snapshot) deletes contract row only, no DB errors

---

## Resolved Decisions

1. ~~Naming collision~~ — `[Contract v{N}] {table_group_name}` bracket prefix; `is_contract_snapshot` is authoritative
2. ~~Performance~~ — `INSERT INTO … SELECT`
3. ~~Historic versions~~ — test count shown as clickable link; add/edit/delete suppressed
