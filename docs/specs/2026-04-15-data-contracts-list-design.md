# Data Contracts List Page — Design Spec

**Date:** 2026-04-15
**Branch:** data-contracts-vibe
**Status:** Implemented — see Implementation Status section below

---

## Implementation Status

**Last updated:** 2026-04-16

### Implemented as designed

| Item | Notes |
|---|---|
| DB schema — `contracts` table | `testgen/template/dbupgrade/0186_incremental_upgrade.sql` |
| DB schema — `contract_versions` table | Same migration; includes partial unique index on `is_current` |
| DB schema — `test_suites.is_contract_suite` | Same migration |
| Navigation — "Data Contracts" menu entry, `order=1` | Sits between Monitors (`order=0`) and Test Suites (`order=2`); TestRunsPage moved to `order=3` to resolve conflict |
| `DataContractsListPage` | `testgen/ui/views/data_contracts_list.py` — cards grouped by table group, status badge, stats row |
| `fetch_contracts_for_project` query | `testgen/ui/queries/data_contract_list_queries.py` — status aggregation via `BOOL_OR`/`BOOL_AND` |
| `DataContractPage` — `contract_id` param | `testgen/ui/views/data_contract.py` — resolves `table_group_id` from `contracts` row |
| `TestSuitesPage` exclusion | `is_contract_suite=TRUE` suites hidden from listing |
| `delete_contract_version` rewrite | `testgen/commands/contract_snapshot_suite.py` — new signature `(contract_id, version)`; promotes previous version to `is_current=TRUE` when deleting the active version |
| `_delete_version_dialog` rewrite + wiring | `testgen/ui/views/dialogs/data_contract_dialogs.py` — rewired to `contract_versions` table; "Delete ver." button added to the detail page toolbar |
| Unit tests — `test_delete_contract_version.py` | `tests/unit/commands/test_delete_contract_version.py` — covers non-current, current (promotes previous), and last-version deletion; uses `contract_id` param |

### Not yet implemented

| Item | Location in spec | Notes |
|---|---|---|
| Unit tests — `tests/unit/test_contract_versions.py` | Testing section | Schema-level constraint tests |
| Unit tests — `tests/unit/test_contracts_list_queries.py` | Testing section | Status aggregation and query tests |
| Unit tests — `tests/unit/test_contract_management.py` | Testing section | Atomic create/delete tests |
| Functional tests — `tests/functional/test_data_contracts_list_page.py` | Testing section | Full list page app tests |
| Functional tests — `tests/functional/test_data_contract_detail_page.py` | Testing section | Detail page app tests |
| Functional tests — `tests/functional/test_test_suites_page.py` | Testing section | `is_contract_suite` exclusion end-to-end |
| `tests/functional/ui/apps/data_contract_delete_version_dialog.py` | — | Functional test script still uses old `table_group_id` signature; needs update to `contract_id` |
| Deactivate / Reactivate contract | `⋮` menu on list page card | Not yet wired up — UI scaffold present but `UPDATE contracts SET is_active` not called |

---

## Overview

Restructures data contracts from one-per-table-group to one-per-test-suite, adds a project-scoped list page as the primary entry point, and introduces a proper `contracts` + `contract_versions` schema. Each contract is co-created with a dedicated test suite. The list page is the only place to create or delete contracts; the detail page is edit + version-save only.

**Fundamental contract authoring rule:** A contract is always created first; its linked test suite is created as a consequence of that action — never the other way around. You never select or convert an existing active test suite into a contract. The wizard (`docs/2026-04-15-create-new-contract-wizard-design.md`) handles the full creation flow: user names the contract, selects a table group, and optionally adds tests — all as part of one guided sequence. The resulting test suite is owned by the contract and hidden from the normal test suite listing.

**Out of scope:** Migration from existing `data_contracts` rows — no production users exist yet.

**Dependency:** The "New Contract" creation flow is defined in `docs/2026-04-15-create-new-contract-wizard-design.md`. The "+ New Contract" button on the list page calls that wizard. The data model in this spec (atomically creating `contracts` + `test_suites` rows) must be reconciled with the wizard spec's completion step.

---

## Data Model

### New table: `contracts`

```sql
CREATE TABLE {schema}.contracts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,
    project_code     TEXT NOT NULL REFERENCES {schema}.projects(project_code),
    table_group_id   UUID NOT NULL REFERENCES {schema}.table_groups(id),
    test_suite_id    UUID NOT NULL REFERENCES {schema}.test_suites(id),
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (name, project_code),  -- contract names are distinct within a project
    UNIQUE (test_suite_id)        -- one contract per linked test suite
);
```

- `name` — human-readable contract name, unique per project
- `project_code` — denormalized from `table_group.project_code` for fast list queries and unique constraint
- `table_group_id` — denormalized for grouping on the list page; derivable via `test_suites` join but avoids it
- `test_suite_id` — the PRIMARY linked test suite, co-created with the contract (`is_contract_suite=TRUE`); UNIQUE — one contract per suite
- `is_active` — soft-disable flag; inactive contracts are visible on the list page (grayed) but read-only on the detail page

### New table: `contract_versions`

Replaces the existing `data_contracts` table.

```sql
CREATE TABLE {schema}.contract_versions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id       UUID NOT NULL REFERENCES {schema}.contracts(id) ON DELETE CASCADE,
    version           INT NOT NULL,
    is_current        BOOLEAN NOT NULL DEFAULT FALSE,
    saved_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    label             TEXT,
    contract_yaml     TEXT NOT NULL,
    term_count        INT NOT NULL DEFAULT 0,
    snapshot_suite_id UUID REFERENCES {schema}.test_suites(id) ON DELETE SET NULL,
    UNIQUE (contract_id, version)
);

-- Enforces exactly one active version per contract at the DB level
CREATE UNIQUE INDEX contract_versions_one_current
    ON {schema}.contract_versions (contract_id)
    WHERE is_current = TRUE;
```

- `is_current` — exactly one `TRUE` per `contract_id`, enforced by the partial unique index
- `term_count` — denormalized count of schema + quality terms in the YAML; populated at save time, used by the list page card to avoid parsing YAML on every render
- `snapshot_suite_id` — per-version copy of the linked test suite's tests; `ON DELETE SET NULL` so deleting a snapshot suite orphans the reference safely rather than blocking the delete
- `CASCADE DELETE` — deleting a contract removes all its versions automatically

### Modified table: `test_suites`

```sql
ALTER TABLE {schema}.test_suites
    ADD COLUMN is_contract_suite BOOLEAN;
```

- `is_contract_suite = TRUE` — marks the PRIMARY linked test suite for a contract. Distinct from `is_contract_snapshot` (per-version copies).
- Both `is_contract_suite` and `is_contract_snapshot` suites are hidden from the Test Suites listing page.

### Version save transaction

Saving a new version is always atomic:

```sql
-- 1. Flip current active version to inactive
UPDATE {schema}.contract_versions
   SET is_current = FALSE
 WHERE contract_id = :contract_id AND is_current = TRUE;

-- 2. Insert new version as current
INSERT INTO {schema}.contract_versions
       (contract_id, version, is_current, label, contract_yaml, term_count, snapshot_suite_id)
VALUES (:contract_id,
        (SELECT COALESCE(MAX(version), -1) + 1
           FROM {schema}.contract_versions
          WHERE contract_id = :contract_id),
        TRUE, :label, :yaml, :term_count, :snapshot_suite_id);
```

---

## Navigation

- **Menu entry:** "Data Contracts" in section "Data Quality Testing", `order=1`
  - Sits between Monitors (`order=0`) and Test Suites (`order=2`)
  - Icon: `contract`
  - Route: `data-contracts`
  - Query param: `project_code`

---

## Pages

### `DataContractsListPage` (new) — route `data-contracts`

**Purpose:** Project-scoped overview of all contracts. Only place to create or delete contracts.

**Layout:**
- Toolbar: contract count summary + "**+ New Contract**" button
- Cards grouped by table group (section headers), sorted alphabetically
- 3-column card grid (responsive)

**Card anatomy (per mockup):**
- Colored top strip (green/amber/red/gray by status)
- Contract name (linked, navigates to detail page)
- Status badge in upper right (Passing / Warning / Failing / No Run)
- Stats row: Version · Terms · Tests
- Footer: "Delete Contract" button (neutral/white style)
- Inactive contracts: card is grayed, badge reads "Inactive"

**Actions:**
- **+ New Contract** → opens the new contract wizard defined in `docs/2026-04-15-create-new-contract-wizard-design.md`. On wizard completion: new `contracts` row + new `test_suites` row (`is_contract_suite=TRUE`) created atomically.
- **Card click** → navigates to `data-contract?contract_id=<uuid>`
- **Delete Contract** → confirmation dialog: "Delete [name] and all N saved versions? This cannot be undone." → `DELETE FROM contracts` (cascades); deletes linked test suite and all snapshot suites.
- **Deactivate / Reactivate** → `⋮` icon button in the card header opens a small menu with "Deactivate" / "Reactivate" → `UPDATE contracts SET is_active = ...`

**List page status computation:**
The status badge and top strip color for each card are derived from the aggregate result of the latest test run on the contract's linked test suite (`contracts.test_suite_id`). Logic:
- Any `Failed` result → **Failing** (red)
- Any `Warning`, none `Failed` → **Warning** (amber)
- All `Passed` → **Passing** (green)
- No test results found → **No Run** (gray)

This is a single query joining `test_suites → test_runs → test_results` for the most recent `test_runs.test_starttime` per contract.

**Can activate:** `session.auth.is_logged_in` + `project_code` in query params

### `DataContractPage` (modified) — route `data-contract`

**Changes from current:**
- Accepts `contract_id` query param instead of `table_group_id`. Resolves `table_group_id` from the `contracts` row.
- `can_activate` changes from `"table_group_id" in st.query_params` to `"contract_id" in st.query_params`.
- Removes: first-time flow, "Delete contract" toolbar button, any "New Contract" entry point.
- Adds: breadcrumb / back-link to the list page (`data-contracts?project_code=...`).
- Inactive contracts open in strict read-only mode — no save, no edit, banner shown.
- Version picker and all queries in `contract_versions.py` that previously filtered by `table_group_id` must be updated to filter by `contract_id`.
- All other behavior (version picker, edit terms, save new version, staleness detection, import/export YAML, regenerate) is otherwise unchanged.

### `TestSuitesPage` (modified)

Add `AND COALESCE(is_contract_suite, FALSE) = FALSE` to the test suite listing query, alongside the existing `is_contract_snapshot` exclusion.

---

## Key Operations

### Create contract
A contract is always created before its test suite — never by selecting or converting an existing one.

1. User clicks "+ New Contract" on the list page — launches the wizard (`docs/2026-04-15-create-new-contract-wizard-design.md`)
2. Wizard collects: contract name (validated unique within project), table group, and optionally guides the user through adding tests
3. On wizard completion, backend atomically:
   - Creates `test_suites` row: `is_contract_suite=TRUE`, `test_suite=<contract name>`, `table_groups_id=<tg_id>`
   - Creates `contracts` row pointing to the new suite
4. No version exists yet; navigating to the detail page shows the first-time flow (generate preview → save as v0)

### Save new version
1. User edits, clicks "Save version" on detail page
2. Single transaction: flip old `is_current=FALSE`, insert new version with `is_current=TRUE`, create snapshot suite copy
3. Detail page reloads on new active version

### Delete contract
1. Confirmation dialog on list page showing version count
2. `DELETE FROM contracts WHERE id=:id` — cascades to all `contract_versions` rows (removing FK references to snapshot suites)
3. Delete per-version snapshot suites (`is_contract_snapshot=TRUE`) — safe now that `contract_versions` rows are gone; `ON DELETE SET NULL` on `snapshot_suite_id` also protects against ordering issues
4. Delete the primary linked test suite (`is_contract_suite=TRUE`)

Note: snapshot suites must be deleted **after** the cascade in step 2, not before — deleting them first would cause an FK violation while `contract_versions.snapshot_suite_id` still references them.

### Deactivate / reactivate contract
- `UPDATE contracts SET is_active = FALSE` — contract visible on list (grayed), detail page read-only
- `UPDATE contracts SET is_active = TRUE` — contract fully editable again

---

## Testing

### Unit tests (`@pytest.mark.unit`)

**`tests/unit/test_contract_versions.py`**
- `test_save_version_flips_is_current` — saving a new version sets `is_current=TRUE` on the new row and `FALSE` on the previous one
- `test_only_one_current_version_per_contract` — the partial unique index prevents two `is_current=TRUE` rows for the same contract
- `test_delete_contract_cascades_to_versions` — deleting a `contracts` row removes all `contract_versions` rows
- `test_contract_name_unique_within_project` — inserting two contracts with the same name + project_code raises IntegrityError
- `test_contract_name_same_name_different_project` — same name in different projects is allowed

**`tests/unit/test_contracts_list_queries.py`**
- `test_fetch_contracts_for_project` — returns only contracts matching `project_code`
- `test_fetch_contracts_grouped_by_table_group` — result is ordered/grouped correctly
- `test_inactive_contract_included_in_list` — `is_active=FALSE` contracts appear in the result
- `test_contract_suite_excluded_from_test_suites_query` — `is_contract_suite=TRUE` suites are not returned by the test suites listing query
- `test_contract_status_aggregation_passing` — all passed results → status is Passing
- `test_contract_status_aggregation_failing` — any failed result → status is Failing regardless of other results
- `test_contract_status_aggregation_warning` — warning present, no failures → status is Warning
- `test_contract_status_aggregation_no_run` — no test results → status is No Run

**`tests/unit/test_contract_management.py`**
- `test_create_contract_creates_test_suite` — contract creation atomically creates a `test_suites` row with `is_contract_suite=TRUE`
- `test_create_contract_rolls_back_on_suite_failure` — if suite creation fails, no `contracts` row is left behind
- `test_delete_contract_removes_suite` — linked test suite is deleted alongside the contract

### UI / app tests (`@pytest.mark.functional`)

**`tests/functional/test_data_contracts_list_page.py`**
- `test_list_page_shows_contracts_for_project` — navigating to `data-contracts?project_code=X` renders cards for all contracts in that project
- `test_list_page_groups_by_table_group` — table group section headers appear correctly
- `test_inactive_contract_card_is_grayed` — inactive contract card has the inactive visual state
- `test_delete_contract_shows_confirmation` — clicking "Delete Contract" shows confirmation dialog with version count
- `test_delete_contract_removes_card` — confirming delete removes the card from the list
- `test_new_contract_button_opens_wizard` — clicking "+ New Contract" opens the wizard entry point
- `test_deactivate_contract_makes_card_grayed` — deactivating a contract via the `⋮` menu updates the card to the inactive visual state
- `test_reactivate_contract_restores_editability` — reactivating sets `is_active=TRUE` and the card returns to normal state

**`tests/functional/test_data_contract_detail_page.py`**
- `test_detail_page_accepts_contract_id_param` — navigating with `contract_id=<uuid>` renders the contract
- `test_detail_page_has_back_link` — back-link to list page is present
- `test_inactive_contract_is_read_only` — inactive contract detail page shows read-only banner and save is disabled
- `test_save_version_creates_new_current` — saving a version on the detail page makes it the active version
- `test_delete_button_absent_from_detail_page` — "Delete contract" toolbar button does not appear

**`tests/functional/test_test_suites_page.py`**
- `test_contract_suite_hidden_from_listing` — test suites with `is_contract_suite=TRUE` do not appear on the Test Suites page

---

## Open Dependencies

| Item | Status |
|---|---|
| New Contract wizard spec | `docs/2026-04-15-create-new-contract-wizard-design.md` — data model completion step must be reconciled with this spec |
| `data-contract` detail page refactor (`contract_id` param) | Depends on this spec |
| DB upgrade script (`0184_incremental_upgrade.sql`) | Part of implementation |

---

## Decisions Log

| Decision | Rationale |
|---|---|
| Name uniqueness is project-scoped | Same contract name in different projects is valid; table-group scope was too narrow |
| `project_code` denormalized onto `contracts` | Avoids join for list queries and enables the unique constraint directly |
| `table_group_id` denormalized onto `contracts` | Avoids join for list page grouping |
| Partial unique index for `is_current` | DB-level enforcement; no application logic needed to prevent two active versions |
| No migration | No production users; start clean |
| Wizard spec is separate | Creation flow has enough complexity to warrant its own design cycle |
