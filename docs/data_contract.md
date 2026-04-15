# Data Contract Feature

## What This Feature Does

A **data contract** in TestGen is a versioned, formal agreement about what a dataset should look like and whether it currently meets that agreement. It takes the test suites you've already defined for a table group — null-rate checks, value ranges, duplicate checks, custom SQL, etc. — and packages them into a versioned YAML document following the [ODCS v3.1.0](https://bitol-io.github.io/open-data-contract-standard/) open standard. That document becomes a stable, exportable record that data consumers, data stewards, and external tools can reference.

From a user's perspective: navigate to a table group, click **Data Contract**, and you get a health dashboard showing how well the current data matches the contract, a full matrix of every schema column and its quality terms, and the ability to save a named version, export the contract as YAML, import edited YAML back in, and track drift between the saved contract and live TestGen state.

**Entry point:** `?table_group_id=<uuid>` on page key `data-contract`. Registered as `AvailablePages.DATA_CONTRACT` in `testgen_component.py`.

---

## Data Contract Use Cases

### Use Case 1: Protect The Output (Hold Myself Accountable)

**The problem:** A data engineer wants to prove that the data they produce meets a defined standard — a "green stamp of approval" that says the output is correct before it goes downstream.

**Example:** An engineer exports 5 tables (300 columns) to an external partner. Before sending, they want to verify the export meets the contract. They set up a contract for those tables and add a test node in their pipeline that runs the contract tests against the tables before the export fires. They also generate an XLSX FIA (File Interchange Agreement) from the contract to send to the receiving party.

**How TestGen supports this:**
- A data engineer creates a contract in TestGen from existing test suites, then calls it via the CLI (`testgen run-tests`) or runs the paired snapshot test suite directly.
- Passing test results, visible in the UI against the contract's paired suite, prove the output meets the contract requirements.
- The contract can be exported as ODCS YAML or as a report to share with downstream consumers.

---

### Use Case 2: Protect The Input (Hold Suppliers Accountable)

**The problem:** A data engineer receives data from a vendor and wants to verify it matches what was agreed upon — the FIA (File Interchange Agreement) or DIA (Data Interchange Agreement) the vendor provided.

**Example:** An engineer receives a DIA spreadsheet from a data vendor. They use an AI tool to convert it to a standard ODCS YAML contract, import it into TestGen, and then run TestGen against each new delivery. The test results provide traceability back to specific contract line items, so discrepancies can be communicated directly to the vendor.

**How TestGen supports this:**
- A data engineer can use AI (e.g. Claude) to convert a vendor spec into an ODCS-standard YAML contract and import it into TestGen via **Import YAML**.
- Alternatively, the engineer loads the vendor data into a table, profiles it, generates tests, and generates a contract from that profiling — letting the data itself define the baseline.
- In both cases, the contract is editable in the TestGen UI and can be re-run on each new delivery to verify compliance.

---

### Use Case 3: Prove The Middle Is Awesome (Show Value of Data Work to Customers)

**The problem:** A data engineer does significant transformation and quality work in an ETL pipeline, but that work is invisible to stakeholders. The contract becomes evidence of the work being done.

**How TestGen supports this:**
- A data engineer takes several test suites — one per transformation stage or table — and combines them into a versioned data contract for a table group.
- The contract version history shows what was tested, when, and whether it passed, serving as an auditable record of data quality work.
- The contract can be shared with customers or stakeholders as proof of the rigor applied to the data.

---

### Use Case 4: Contract As Shared Interface To Data Stewards and Business Owners

**The problem:** Technical test definitions are too complex for business stakeholders to engage with directly. A data contract bridges that gap by surfacing quality terms in plain language.

**How TestGen supports this:**
- In any of the use cases above, the data contract UI becomes a shared communication layer between engineers, data stewards, and business owners.
- Stakeholders can view the contract health dashboard, inspect terms by column, discuss definitions, and understand what the data guarantees — without needing to understand the underlying SQL tests.
- The contract can be exported, versioned, and iterated on collaboratively through the UI.

---

## Start Here: Key Concepts

Before reading the rest of this document, internalize these five concepts. Everything else builds on them.

### 1. The Snapshot Suite — the central invariant

Every saved contract version has a paired **snapshot test suite** with `is_contract_snapshot = TRUE`. That suite is a frozen copy of the in-scope tests at save time. It never changes unless you explicitly edit the contract through the UI or re-save.

This matters for your code in two ways:

- **All source-suite queries must exclude snapshot suites.** Use `AND COALESCE(ts.is_contract_snapshot, FALSE) = FALSE` everywhere. If you add a new query over `test_suites` or `test_definitions` and forget this, snapshot tests will bleed into profiling runs, test generation, and other views.
- **The diff and staleness views compare live TestGen state against the snapshot, not the other way around.** The snapshot is the "agreed" state; live TestGen is the "current" state.

Think of a snapshot suite like a git tag: an immutable, named point in time. The live test suites are the working tree.

### 2. ODCS and the contract YAML

[ODCS v3.1.0](https://bitol-io.github.io/open-data-contract-standard/) defines a standard YAML format for data contracts. TestGen exports to and imports from this format. The YAML has several top-level sections:

- `fundamentals` — version, status, domain, description, SLA properties
- `schema` — one entry per table, with column-level metadata (type, constraints, governance fields)
- `quality` — one rule per test definition, with metric, operator, threshold, severity
- `servers`, `references`, `compliance` — source system metadata

On import, `schema`, `servers`, and `references` are read-only (TestGen is the source of truth for column types). Only `quality` rules and some `fundamentals` fields are writable via import.

### 3. Staged changes / pending edits

When a user edits a term inline — adjusting a threshold, changing a severity, adding a description — those changes are held in `st.session_state["dc_pending:{tg_id}"]` until the user clicks Save. They are **staged**, not committed.

If you are writing code that reads contract state, be aware that `st.session_state` may hold edits not yet in the DB. The YAML in session state is the in-progress version; the DB and snapshot suite reflect the last saved state.

### 4. Staleness

Staleness is a passive detection: when the live TestGen DB has drifted from the saved contract (schema changed, tests added or removed), a banner appears. `compute_staleness_diff` in `contract_staleness.py` computes this diff. It is distinct from the user-initiated **Regenerate** action, which re-baselines the contract from the current DB state.

### 5. Enforcement tiers

Every contract term is classified into one of three enforcement tiers by `_classify_enforcement_tier` in `data_contract_props.py`:

| Tier | Meaning | Examples |
|---|---|---|
| `db` | DDL-type terms; enforced by the database schema | column type, NOT NULL, primary key |
| `unf` | Observed but undeclared; not actively enforced | profiling stats like min/max, detected data type |
| `tg` | TestGen-enforced; backed by an active test or monitor | `Missing_Pct <= 5`, `Row_Ct >= 1000` |

---

## File Map

| Layer | File | Role |
|---|---|---|
| View | `testgen/ui/views/data_contract.py` | Page render, toolbar, event handlers, pending edits |
| Frontend | `testgen/ui/components/frontend/js/pages/data_contract.js` | VanJS UI, term chips, selection mode, modals via `emitEvent` |
| Props | `testgen/ui/views/data_contract_props.py` | Props builder, `_classify_enforcement_tier`, coverage tiers |
| YAML helpers | `testgen/ui/views/data_contract_yaml.py` | YAML mutation helpers, `_delete_term_yaml_patch` |
| DB queries | `testgen/ui/queries/data_contract_queries.py` | `_fetch_test_statuses`, `_persist_governance_deletion`, `_GOVERNANCE_LABEL_TO_FIELD` |
| Dialogs | `testgen/ui/views/dialogs/data_contract_dialogs.py` | All `@st.dialog` save/edit/delete dialogs; `_clear_contract_cache` |
| Export | `testgen/commands/export_data_contract.py` | ODCS YAML generation |
| Import | `testgen/commands/odcs_contract.py` | `run_import_contract`, `get_updated_yaml`, `ContractDiff` |
| Staleness | `testgen/commands/contract_staleness.py` | `compute_staleness_diff`, `compute_term_diff`, `TermDiffResult` |
| Versions | `testgen/commands/contract_versions.py` | `save_contract_version`, `load_contract_version`, `update_contract_version` |
| Snapshot | `testgen/commands/contract_snapshot_suite.py` | `create_contract_snapshot_suite`, `sync_import_to_snapshot_suite`, `delete_contract_version` |

### Key architectural patterns

**Modal pattern — always use emitEvent:** Custom component iframes clip `position: fixed/absolute` elements. Any modal or dialog MUST go through: JS emits an event via `emitEvent` → Python `event_handlers` → `@st.dialog`. Never use VanJS overlays or positioned elements inside the component iframe.

**`event_handlers` vs `on_change_handlers`:** Use `event_handlers` when the handler needs to call `st.rerun()`. Dialogs always need `st.rerun()`, so dialog-triggering events go in `event_handlers`. `on_change_handlers` does not support `st.rerun()`.

**YAML caching:** The contract YAML string is cached in `st.session_state["dc_yaml:{tg_id}"]` to avoid re-fetching on every Streamlit rerun. Test run results are NOT cached — fetched fresh from DB on each render via `_fetch_test_statuses()`. Never use `lastResult` from the cached YAML; it may be stale.

**Cache management:** `_clear_contract_cache(table_group_id, *, also_anomalies=False)` clears all 7 session state keys:
```python
_CONTRACT_CACHE_KEYS = ("dc_pending", "dc_yaml", "dc_version", "dc_run_dates", "dc_gov", "dc_term_diff", "dc_suite_scope")
```
Call this on every save, import, refresh, and delete. Use `also_anomalies=True` only in the delete version dialog.

---

## Data Flow Walkthroughs

These traces walk through what actually happens in the code for common operations. Read these before making changes to the page.

### Page load (existing contract)

1. `DataContractPage.render(table_group_id)` is called by the Streamlit router.
2. If no saved version exists → `_render_first_time_flow()` (bootstrap path).
3. Otherwise: `_load_contract_state()` fetches the version record and YAML from DB (or returns the cached value from `dc_yaml` session key).
4. `_build_props()` calls `data_contract_props.py` to build the full props dict: schema terms, quality rules, governance fields, enforcement tiers, coverage counts.
5. `_render_health_dashboard()` renders the three top cards using `_fetch_test_statuses()` and `_fetch_anomalies()` (live DB calls, not cached).
6. `testgen_component("data_contract", props=props, event_handlers=..., on_change_handlers=...)` renders the VanJS component with props injected.
7. If any `event_handlers` keys have values in session state (from a previous JS event), the corresponding Python handler is called before rendering.

### User edits a term threshold and saves

1. User clicks a test chip → JS emits `EditRuleClicked { rule_id }` → Python `on_edit_rule_clicked` → `@st.dialog` opens (`_edit_rule_dialog`).
2. User changes the threshold → clicks Save in dialog.
3. Python writes the new threshold to `st.session_state["dc_pending:{tg_id}"]` as a YAML patch and calls `safe_rerun()`.
4. On next render, the staged change appears in the toolbar warning bar ("N staged changes — not yet saved").
5. User clicks **Save version (N)** → `_save_version_dialog` opens.
6. User confirms → `_persist_pending_edits()` applies YAML patches → `save_contract_version()` writes to `data_contracts` table and creates a new snapshot suite via `create_contract_snapshot_suite()` → `_clear_contract_cache()` → `safe_rerun()`.

### YAML import

1. User clicks **Import YAML** in toolbar → `_import_yaml_dialog` opens (Python `@st.dialog`).
2. User uploads a `.yaml` file → Python runs `run_import_contract(yaml_content, table_group_id, dry_run=True)` — returns a `ContractDiff` with no DB writes.
3. Preview is stored in `st.session_state["dc_import_preview:{tg_id}"]` → `safe_rerun()`.
4. Confirmation dialog renders from the staged preview: accepted/skipped counts, create/update breakdown, warnings, orphaned IDs.
5. User clicks **Confirm Import** → `run_import_contract(yaml_content, table_group_id, dry_run=False)` runs for real.
6. `sync_import_to_snapshot_suite(snap_id, created_ids, updated_ids, [])` mirrors changes to the snapshot suite.
7. `_clear_contract_cache()` → result banner shown.

### Regenerate

1. User clicks **Regenerate** → `_regenerate_dialog()` opens.
2. User confirms (checkbox if pending edits exist) → `_capture_yaml()` calls `run_export_data_contract()` to build fresh YAML from current DB state.
3. `save_contract_version()` writes the new version + creates a new snapshot suite.
4. `_clear_contract_cache()` → page reloads at new version.

---

## Contract Lifecycle

A data contract passes through these lifecycle activities:

1. **Bootstrap (Create)** — First-time flow generates the initial contract YAML from the current DB state (schema + profiling stats + active test definitions). Entry point: `_render_first_time_flow()`.

2. **Inline edit** — Users edit governance terms (description, CDE, PII), test rule thresholds/tolerances/severity, and delete terms directly in the UI. Edits are staged as pending changes (`dc_pending:{tg_id}` session state) and committed via Save.

3. **Save version** — Creates a named, timestamped snapshot of the current state. When pending edits exist, the user can update the current version in-place (`_update_version_dialog`) or promote to a new version number (`_save_version_dialog`).

4. **Export YAML** — Download the current contract as an ODCS v3.1.0 YAML file (read-only; enables external editing).

5. **Import YAML** — Upload a modified ODCS YAML to sync changes back to TestGen. Rules without an `id` field are created as new tests; rules with an `id` update the matching test. Entry point: `run_import_contract()`.

6. **Regenerate** — Re-export from the current DB state and save as a new version, picking up schema changes, new/removed tests, and updated profiling stats. Entry point: `_regenerate_dialog()`.

7. **Staleness detection + response** — Passive lifecycle event: the system detects when the DB has drifted from the saved contract (schema changes, test additions/removals) and shows a banner. The user reviews a diff (`compute_staleness_diff`) and can accept or dismiss. Distinct from Regenerate, which is user-initiated.

8. **Version navigation** — Switch between historical read-only snapshots. The latest version is always editable; older versions are read-only.

9. **Delete version** — Removes a specific saved version and its paired snapshot test suite. Deleting the latest version promotes the previous version to active. Entry point: `_delete_version_dialog()`.

```
Bootstrap → Edit → Save version ──────────────────────────────┐
                 ↑ Import YAML (download → edit externally → upload)  │
                 ↑ Regenerate (re-export from DB)              │
                 ↑ Respond to staleness (DB drift detected)    │
                                                               ↓
                                               Delete version (any version)
```

There are exactly three supported paths to creating or updating a contract:

1. **Start from existing tests** — Begin with existing TestGen test suites, edit contract terms in the UI, and click **Save version**. Saving creates a new snapshot suite that freezes the contract state.

2. **Upload YAML** — Upload an ODCS v3.1.0 YAML file directly. TestGen imports the rules and syncs the snapshot suite. The contract is static once imported.

3. **Round-trip editing** — Download the contract YAML, edit it externally (in an IDE, or collaboratively with stakeholders), and re-upload. Each re-upload is applied against the current version's snapshot suite; save a new version when the round-trip is complete.

**Regenerate** creates a fresh version from the current live DB state (new snapshot suite, version bump). Use it when re-baselining, not for targeted edits.

---

## DB Schema

| Column | Table | Type | Purpose |
|---|---|---|---|
| `include_in_contract` | `test_suites` | `BOOLEAN NOT NULL DEFAULT TRUE` | Controls which suites are in scope for the contract |
| `is_monitor` | `test_suites` | `BOOLEAN` | Monitor suites — excluded from contract test counts and suite picker |
| `is_contract_snapshot` | `test_suites` | `BOOLEAN NOT NULL DEFAULT FALSE` | Marks a suite as a locked snapshot created at save time; excluded from all source-suite queries |
| `snapshot_suite_id` | `data_contracts` | `UUID REFERENCES test_suites(id) ON DELETE SET NULL` | Links each saved contract version to its paired snapshot test suite |
| `source_test_definition_id` | `test_definitions` | `UUID` | On snapshot suite rows, points back to the source test definition that was copied; no FK constraint |

Migrations:
- `testgen/template/dbupgrade/0183_incremental_upgrade.sql` — adds `include_in_contract`
- `testgen/template/dbupgrade/0185_incremental_upgrade.sql` — adds `is_contract_snapshot` on `test_suites`, `snapshot_suite_id` on `data_contracts`, `source_test_definition_id` on `test_definitions`

---

## Contract Snapshot Suite

When a contract version is saved, a **snapshot test suite** (`[Contract vN] {table_group_name}`) is created that captures the exact set of in-scope tests at that moment. Each saved version has its own snapshot suite linked via `data_contracts.snapshot_suite_id`.

### Save behavior

| Button | Condition | Action |
|---|---|---|
| **Save ● (n)** | Pending edits exist in session state | In-place update — `update_contract_version` rewrites YAML for the current version; no new snapshot suite, no version bump |
| **Save version** | No pending edits | Creates a new version + new snapshot suite via `create_contract_snapshot_suite` |
| **Regenerate** | Always | Re-baselines from the current live DB state; saves as a new version + new snapshot suite |

**Save ● (n)** is the only action that modifies an existing snapshot in place (YAML rewrite, no version bump). Once **Save version** is clicked, the snapshot is fully frozen.

### Snapshot suite filters

All queries that operate on source suites must exclude snapshot suites:
```sql
AND COALESCE(ts.is_contract_snapshot, FALSE) = FALSE
```
This applies to:
- `_fetch_suite_scope` (`data_contract_queries.py`)
- `_fetch_test_statuses` (`data_contract_queries.py`)
- `_fetch_last_run_dates` (`data_contract_queries.py`)
- `_fetch_suite_scope` / `compute_term_diff` (`contract_staleness.py`)
- `_fetch_tests` / `_fetch_test_run_history` (`export_data_contract.py`)

### Sync on mutation

All test mutations in the contract UI are immediately mirrored to the snapshot suite:

- **Single-test delete** (`_edit_rule_dialog`): calls `sync_import_to_snapshot_suite(snap_id, [], [], [rule_id])`
- **Bulk delete** (`on_bulk_delete_terms`): calls `sync_import_to_snapshot_suite(snap_id, [], [], deleted_ids)` after YAML patch
- **YAML import** (`on_import_contract`): calls `sync_import_to_snapshot_suite(snap_id, created_ids, updated_ids, [])` for created/updated tests
- **Add test** (`on_add_test`): opens `add_test_dialog` targeting the snapshot suite directly

### Add test button

`showAddTest = !!(versionInfo.snapshot_suite_id && versionInfo.is_latest)` — only the latest snapshot-backed version shows the button. Emits `AddTestClicked { tableName, colName }` → routes to `on_add_test` in `data_contract.py`.

### Staleness diff — quality suppression

`compute_staleness_diff` accepts `snapshot_suite_id: str | None`. When non-null, `quality_changes = []` (tests are locked to the snapshot suite and always in sync). Schema, governance, and suite-scope changes are still computed.

---

## JS Events (JS → Python)

All live events go through `event_handlers` (supports `st.rerun()`):

| Event | Payload | Handler |
|---|---|---|
| `EditRuleClicked` | `{ rule_id }` | Open `@st.dialog` for test term edit |
| `TermDetailClicked` | `{ term, tableName, colName }` | Open `@st.dialog` for governance or read-only term view |
| `SuitePickerClicked` | — | Open `@st.dialog` suite picker (include/exclude suites) |
| `GovernanceEditClicked` | `{ tableName, colName }` | Open `@st.dialog` for governance term edit |
| `BulkDeleteTermsClicked` | `{ terms: [...] }` | Multi-select bulk delete; each term carries `{table, col, source, name, rule_id}` |
| `ImportContractClicked` | `{ payload: <yaml_string> }` | Dry-run preview, stages result in `import_preview_key`, reruns; confirmation dialog shown on next cycle |
| `AddTestClicked` | `{ tableName, colName }` | Opens `add_test_dialog` for creating new tests |

---

## Feature Details

### Health Dashboard

Three top cards rendered on every page load. Test statuses are fetched fresh from the DB via `_fetch_test_statuses()` — the cached YAML `lastResult` field is never used.

- **Contract Term Coverage** — percent of schema columns with at least one non-schema quality term; includes a filter link to uncovered columns.
- **Contract Term Differences** — counts of same/changed/new/deleted terms vs. the saved YAML snapshot. Card label includes the version number (e.g. "Version 12 Contract Term Differences"). Each status row is clickable and deep-links to the Contract Term Differences tab.
- **Contract Term Compliance** — enforcement tier breakdown (DB enforced / unenforced / TestGen enforced) with per-monitor, per-test, and hygiene status counts. Scope is limited to contract terms only — TestGen tests outside the saved YAML are excluded.

When no saved version exists, Cards 2 and 3 show a "No contract saved yet" placeholder.

---

### Coverage Matrix

Term grid across all schema columns, organized by enforcement tier:

- `db` — DDL-type terms (data type, not-null, primary key)
- `unf` — observed/undeclared terms (sourced from profiling, not yet asserted)
- `tg` — TestGen-enforced (test and monitor suite definitions)

Tier classification: `testgen/ui/views/data_contract_props.py:_classify_enforcement_tier`

Monitor suites (`is_monitor=True`) are excluded from the suite picker and test count display, but kept for navigation fallback.

---

### YAML Export

Exports a full ODCS v3.1.0 YAML document covering:

- `fundamentals` — version, status, domain, dataProduct, description, slaProperties
- `schema` — columns with physicalType, logicalType, constraints, governance fields (CDE, PII, description), and `customProperties[testgen.*]` for additional metadata
- `quality` — one rule per test definition with operator, threshold, tolerance, severity, suiteId
- `servers`, `references`, `compliance` sections

Entry point: `testgen/commands/export_data_contract.py`

The frontend triggers a browser download (`a.download`) directly from the YAML string in props — no `emitEvent` round-trip needed.

**Read-only on import:** `schema`, `servers`, and `references` sections are ignored by the importer; only `quality` and `fundamentals` are writable.

---

### YAML Import

Accepts an ODCS v3.1.0 YAML file and applies changes back to TestGen.

**Supported mutations:**
- Create new tests (rules without `id`) → new UUID written back to YAML
- Update existing tests (rules with `id`) — threshold, tolerance, severity, description, custom_query
- Update contract fundamentals — version, status, description.purpose, domain, dataProduct, slaProperties.latency
- Update governance fields from `schema[].properties[]` — description, CDE, classification, and `customProperties[testgen.*]` fields

**Entry points:**
- `testgen/commands/odcs_contract.py:run_import_contract` — validates and applies (use `dry_run=True` for preview)
- `testgen/commands/odcs_contract.py:get_updated_yaml` — writes new UUIDs back into the uploaded YAML
- `testgen/ui/views/data_contract.py:on_import_contract` — event handler; busts YAML/anomaly/version caches on success

**Result object:** `ContractDiff` — contains `.test_inserts`, `.test_updates`, `.contract_updates`, `.table_group_updates`, `.warnings`, `.errors`, `.has_errors`, `.total_changes`, `.skipped_rules`, `.no_change_rules`, `.orphaned_ids`, `.new_id_by_index`.

**Validation (document-level, abort on error):**
- `apiVersion` must be `v3.1.0`; `kind` must be `DataContract`; `id` required
- Valid `status` values: `active`, `deprecated`, `draft`, `proposed`, `retired`
- Table group must exist in DB

**Rule-level skips (WARN, rule skipped, import continues):**
- Unsupported metrics: `missingValues`
- Unsupported operators: `mustNotBe`, `mustNotBeBetween`
- `invalidValues` without `arguments.validValues` or `arguments.pattern`
- Non-TestGen engines: `soda`, `greatExpectations`, `montecarlo`, `dbt`
- `type: text` — silently skipped (no warning)
- Missing `type`, `metric`, `element`, or threshold
- `id` not found in DB or belongs to different table group
- Attempt to change `metric` or `element` on an existing test (immutable)

**Known gaps:**
- Deleting a test via YAML (omitting a rule that exists in DB) is intentionally not supported — produces an orphan warning, not a delete.
- Metric-type changes on existing tests require delete + re-create.

For exhaustive YAML test cases, see [Appendix: YAML Import Test Cases](#appendix-yaml-import-test-cases).

---

### Bulk Multi-Select Delete

User flow:
1. Click **Select** in the terms toolbar → enters selection mode (`_selectionMode.val = true`)
2. Checkboxes appear on all term chips
3. Click individual chips to toggle selection; running count appears in toolbar
4. Click **Delete contract terms** → shows "Are you sure?" confirmation
5. Click **Yes, delete** → `emitEvent('BulkDeleteTermsClicked', { terms: [...] })` → Python `on_bulk_delete_terms`

What gets deleted by term source:

| Source | Action |
|---|---|
| `test` / `monitor` | Rule removed from `quality` array in YAML by `rule_id` |
| `ddl` | Field (`physicalType`, `required`, `_logicalTypeOptions.primaryKey`) removed from `schema[].properties[]` |
| `profiling` | `logicalTypeOptions` subfield (`minimum`, `maximum`, `minLength`, `maxLength`, `format`, `logicalType`) removed from `schema[].properties[]` |
| `governance` | `criticalDataElement` or `description` removed from YAML **and** DB column in `data_column_chars` reset via `_persist_governance_deletion` |

**Atomicity:** Governance DB writes happen before YAML is committed to session state. If any DB write fails, YAML is not updated and an error banner is shown.

Key files:
- `testgen/ui/components/frontend/js/pages/data_contract.js` — `enterSelectionMode`, `exitSelectionMode`, `confirmDelete`, `BulkDeleteTermsClicked`
- `testgen/ui/views/data_contract.py:on_bulk_delete_terms` — handler
- `testgen/ui/views/data_contract_yaml.py:_delete_term_yaml_patch` — YAML field removal
- `testgen/ui/queries/data_contract_queries.py:_persist_governance_deletion` — DB write for governance deletions
- `testgen/ui/queries/data_contract_queries.py:_GOVERNANCE_LABEL_TO_FIELD` — label → (db_column, reset_value) map with allowlist enforcement

Known limitations:
- Table-level governance terms (not column-scoped) are not deletable.
- PII term editing/deletion requires `view_pii` permission.
- Governance terms are sourced from `data_column_chars` DB, not YAML — deletions must always write to DB, not just YAML.

---

### Contract Term Differences

Compares the saved contract YAML snapshot against the current live TestGen state and classifies every quality term by drift status.

**Term statuses:**
```python
TermStatus = Literal["same", "changed", "new", "deleted"]
```

| Status | Meaning |
|---|---|
| `same` | Exists in saved contract and current TestGen; no meaningful change |
| `changed` | Exists in both; threshold or config differs |
| `new` | In current TestGen but absent from the saved contract |
| `deleted` | In saved contract but no longer in current TestGen |

**Key rule:** Terms absent from the saved contract YAML (i.e. previously intentionally deleted) are never surfaced as "new". The diff is always from the saved contract's perspective.

**Entry point:** `compute_term_diff(table_group_id, saved_yaml) -> TermDiffResult` in `contract_staleness.py`.

**Algorithm:**
1. Parse saved YAML `quality` array → build index `{rule_id: rule}`
2. Query current TestGen test definitions (excluding snapshot suites and referential tests)
3. For each rule in saved YAML: match against live TestGen → `same`, `changed`, or `deleted`
4. For each TestGen definition not in saved YAML → `new`
5. Classify each TestGen-enforced entry by monitor / test / hygiene subtype
6. Count enforcement tiers using `_classify_enforcement_tier`

**Post-implementation bug fixes applied:**
- Float/string threshold mismatch: normalize both sides to float before comparison
- Range thresholds always showing "changed": fetch `lower_tolerance` + `upper_tolerance` separately and build a `"lower,upper"` comparison string
- Referential tests (e.g. `Aggregate_Balance`) appearing as "new": filter by joining `test_types` and excluding `test_scope = 'referential'`

---

## CLI Interface

```bash
# Export to stdout
testgen export-data-contract -t <table-group-id>

# Export to file
testgen export-data-contract -t <table-group-id> -o orders_contract.yaml

# Import from file
testgen import-data-contract -t <table-group-id> -f orders_contract.yaml

# Dry run — preview changes without applying
testgen import-data-contract -t <table-group-id> -f orders_contract.yaml --dry-run

# Create a brand-new contract for a table group from an ODCS YAML file
testgen create-contract -tg <table-group-id> -i orders_contract.yaml [--label "v1 baseline"]

# Run all in-scope (non-snapshot, non-monitor) test suites for a table group's contract
testgen run-contract-tests -tg <table-group-id>
```

`run-contract-tests` queries `test_suites` where `include_in_contract IS TRUE AND is_monitor IS NOT TRUE AND is_contract_snapshot IS NOT TRUE`, runs each suite via `run_test_execution`, and exits non-zero if any suite fails.

Python API:
```python
from testgen.commands.odcs_contract import run_import_contract

diff = run_import_contract(yaml_content, table_group_id, dry_run=True)
print(diff.summary())

diff = run_import_contract(yaml_content, table_group_id, dry_run=False)
```

---

## Testing

### Unit Tests

534 data-contract unit tests across 17 files. **All 534 passing as of 2026-04-15.**

```bash
pytest -m unit tests/unit/
```

| File | Lines | Covers |
|---|---|---|
| `tests/unit/commands/test_data_contract_export.py` | 827 | Export mapping, anomaly criteria, YAML output |
| `tests/unit/commands/test_odcs_contract.py` | 1429 | Import validation, diff, apply, CREATE/UPDATE/WRITE-BACK round-trip; `Test_ContractDiffRuleCounters` |
| `tests/unit/ui/test_data_contract_page.py` | 815 | Page registration, coverage tiers, JS link hrefs, `Test_TermCountConsistency` |
| `tests/unit/ui/test_contract_pending_edits.py` | 236 | Pending edit accumulation, YAML patching, persistence helpers |
| `tests/unit/ui/test_contract_term_deletion.py` | 270 | All 13 deletable term types across DDL (4), Profiling (6), Governance (3); error cases |
| `tests/unit/ui/test_bulk_delete_terms.py` | 285 | Multi-select bulk delete across governance, test, and hygiene term types |
| `tests/unit/commands/test_contract_staleness.py` | 472 | `compute_staleness_diff` — schema, quality, governance, and suite scope diffs |
| `tests/unit/commands/test_contract_versions.py` | 258 | `save_contract_version`, `load_contract_version`, `list_contract_versions`, staleness marking |
| `tests/unit/commands/test_staleness_diff.py` | 449 | Threshold comparison helpers; range vs scalar; float/string normalization |
| `tests/unit/commands/test_staleness_detection.py` | 117 | Staleness trigger integration |
| `tests/unit/commands/test_contract_snapshot_suite.py` | 415 | `create_contract_snapshot_suite`, `sync_import_to_snapshot_suite`, `delete_contract_version` |
| `tests/unit/commands/test_delete_contract_version.py` | 118 | Delete contract version cleanup and cascade behavior |
| `tests/unit/commands/test_data_contract_cli.py` | 264 | `create-contract` and `run-contract-tests` CLI commands |
| `tests/unit/commands/test_staleness_diff_snapshot.py` | 170 | Staleness diff with snapshot suite quality suppression |
| `tests/unit/ui/test_contract_on_term_detail_snapshot.py` | 127 | Term detail snapshot rendering |
| `tests/unit/ui/test_contract_dialog_warnings.py` | 173 | Dialog warning states and confirmation flows |
| `tests/unit/ui/test_contract_query_exclusions.py` | 96 | Snapshot suite filter exclusions in all DB queries |

### UI Tests (AppTest)

Streamlit's `AppTest` framework exercises the Data Contract page without a running browser or live database.

```bash
pytest -m functional tests/functional/ui/test_data_contract_apptest.py
```

**App scripts:**

`tests/functional/ui/apps/data_contract_first_time_flow.py` — Loaded by `AppTest.from_file()` for the main page tests. Stubs `streamlit.components.v1.declare_component` and all external I/O patches (`TableGroup.get_minimal`, `_check_contract_prerequisites`, `_capture_yaml`, `_fetch_test_statuses`, `_fetch_anomalies`, save-dialog dependencies).

`tests/functional/ui/apps/data_contract_import_confirm.py` — Standalone script for testing `_confirm_import_dialog` directly. Selects test scenarios via `dc_test_confirm_scenario` session state key. Scenarios: `creates`, `errors`, `governance`, `warnings`, `orphans`.

**Test classes:**

| Class | Tests | What it covers |
|---|---|---|
| `Test_DataContractPageLoad` | 3 | Page renders without exception; table group name flows to save dialog; `table_group_id` query param correctly set |
| `Test_FirstTimeFlow` | 4 | "No contract saved yet" heading appears; prerequisite rows show green; "Generate Contract Preview →" button present |
| `Test_GeneratePreview` | 4 | Clicking preview shows Coverage card; "Save as Version 0" button appears; "← Back" returns to prerequisites |
| `Test_SaveDialog` | 5 | Save dialog opens; confirms "Version 0"; shows snapshot suite name `[Contract v0] Test Orders`; Save and Cancel buttons present |
| `Test_ImportConfirmDialog` | 10 | Dialog renders; accepted/skipped metrics; create/update/no-change breakdown; Confirm and Cancel; error path; governance updates; warnings expander; orphaned IDs |

**AppTest limitations:**
- `st.html` is not accessible — page header title is rendered via `st.html`, which `AppTest` cannot inspect.
- JS components do not execute inside `AppTest` — the VanJS frontend and custom iframes are not runnable. Navigation is simulated by setting `table_group_id` as a query parameter.

---

## Implementation Notes

### Shared Utilities

`_pii_flag_to_classification(pii_flag: str) -> str` lives in `export_data_contract.py` and is imported by `contract_staleness.py`. Do not duplicate this mapping.

### HTML Escaping

All user-sourced strings rendered inside term cards (descriptions, classification values, test threshold expressions) must use `html.escape(value, quote=True)`. Never use manual `.replace("<", "&lt;")` chains — they miss `&`, `"`, and `'`.

### SQL Safety

Never f-string-interpolate UUIDs or user-supplied values into SQL. Use parameterized queries (`%s` placeholders with a parameters tuple). Use `CAST(:x AS uuid)` — never `::uuid` — in SQLAlchemy queries (conflicts with `:param` binding syntax).

### Logging

Use `_log = logging.getLogger(__name__)` throughout all data contract modules. Do not mix with the uppercase `LOG` pattern used elsewhere. Silent exception swallowing (`bare except: pass`) must log at `WARNING` level with `exc_info=True`.

---

## Planned Work

### 1. Create New Contract Terms Directly from the UI

Users should be able to add governance and schema terms (description, CDE, PII, data type, etc.) to a column directly from the Data Contract page, without leaving the contract view.

**Open questions:**
- Which term types are in scope for inline creation (governance only, or DDL/profiling too)?
- Should this be an inline edit on the term chip or a modal?

---

### 2. Create New Tests Directly from the Contract UI

Users should be able to author a new quality test (e.g. `Missing_Pct`, `LOV_Match`, `CUSTOM`) for any column directly from the Data Contract page.

**Open questions:**
- Which test types should be creatable inline vs. requiring the full test editor?
- How does the new test get assigned to a suite?

---

### 3. Flag TestGen-Only Tests Not Part of the ODCS Standard

Some TestGen test types (e.g. `Avg_Shift`, `Distribution_Shift`, `Schema_Drift`, `Aggregate_Balance`) have no equivalent in the ODCS v3.1.0 `library` metric vocabulary. These should be clearly labeled as "TestGen extension" in the contract view.

**Open questions:**
- Where should the label appear — chip badge, tooltip, export annotation?
- Should the YAML importer warn when it encounters a `vendor: testgen` type not in the standard library?

---

### 4. ~~Governance Fields Writable on YAML Import~~ ✅ Implemented

The `schema` section now round-trips fully. `compute_import_diff` reads governance fields from `schema[].properties[]` — both ODCS standard fields and `customProperties[testgen.*]` entries — and writes them to `data_column_chars`.

Also shipped: export now writes profiling stats and DDL constraints as `customProperties[testgen.*]`; `pii_flag` stored as both `classification` (ODCS standard, lossy) and `testgen.pii_flag` (lossless round-trip); backward compatibility via `_prop_opts()` bridge helper.

---

### 5. Test Deletion via YAML Import

Currently, omitting a rule from an uploaded YAML that exists in the DB produces an orphan warning and no action. This should be an opt-in (e.g. `--allow-deletes` flag or document-level `allowDeletions: true`) to avoid accidental data loss.

**Open questions:**
- Should deletion be opt-in at the document level or via an import UI toggle?
- Should deleted tests be hard-deleted or soft-deleted (`test_active = 'N'`)?

---

### 6. Version-to-Version Diff

Today the Contract Term Differences tab always compares a saved version against the current live TestGen state. There is no way to compare two saved snapshots against each other (e.g. v3 vs. v7).

**Open questions:**
- Separate "Compare versions" view or an extension of the existing Differences tab with a version picker for both sides?
- Purely YAML-based diff or include live test status for each version?

---

### 7. Bulk Governance Edit

The symmetric operation to bulk delete — selecting multiple columns and setting a governance field value across all of them at once — does not exist. It would reuse the existing selection mode infrastructure in `data_contract.js`.

**Open questions:**
- Which governance fields should be bulk-settable?
- Should bulk edit open a modal or use a quick-pick dropdown in the toolbar?

---

### 8. ~~Run Contract Tests from the Contract Page~~ ✅ Implemented (CLI)

`testgen run-contract-tests -tg <table-group-id>` runs all in-scope suites. A UI trigger from within the contract page remains a potential future enhancement.

---

### 9. Contract Compliance Notifications

When a saved contract's test results degrade, there is no alert. The email notification infrastructure already exists in `testgen/common/notifications/`. A contract-specific notification firing when `tg_test_failed` or `tg_monitor_failed` goes above zero would be a low-cost addition.

**Open questions:**
- Fire after every test run, or only when status transitions from passing to failing?
- Reuse the existing `TestRunNotification` template or a contract-specific one?

---

### 10. YAML Session State Staleness Detection

The contract YAML cached in `st.session_state` can silently diverge from the DB if tests are edited in another browser tab during the same session. A lightweight DB fingerprint check (comparing max `last_modified` on `test_definitions` against a value captured at page load) could detect this.

**Open questions:**
- Check on every rerun, or only on explicit user actions (save, run)?
- Block saves or just show a warning banner?

---

### 11. Coverage Quality Distinction

The Coverage card counts a column as "covered" if it has any non-schema term, including observed DDL terms like `physicalType`. A finer breakdown — "has at least one quality test" vs. "has only schema/governance terms" — would make the metric more meaningful.

**Open questions:**
- Two coverage percentages (schema vs. quality coverage), or replace the metric with the stricter definition?
- Should the Coverage Matrix visually distinguish columns with only schema terms?

---

## Known Issues

All critical and important issues from the 2026-04-15 code review have been fixed. 534/534 unit tests passing.

### Minor (open)

- **Inconsistent `is_contract_snapshot` filter idioms** — three variants in use: `COALESCE(ts.is_contract_snapshot, FALSE) = FALSE`, `is_contract_snapshot IS NOT TRUE`, and `COALESCE(...) IS NOT TRUE`. All are functionally equivalent given `NOT NULL DEFAULT FALSE`, but CLAUDE.md specifies the `COALESCE(...) = FALSE` form. Affected: `data_contract_queries.py:120`, `contract_staleness.py:696`, `export_data_contract.py:359/377/443`.

- **Missing `CAST(:x AS uuid)` in many new queries** — `table_groups_id = :tg_id` is used throughout without `CAST`. Works in practice (PostgreSQL implicitly casts), but inconsistent with the project standard.

---

## UI Polish To-Dos

Remaining items from the UI design review (`docs/ui_design_review_data_contract.md`). Items are ordered by effort — quick wins first.

### Quick Wins

- **Delete button destructive styling** — The Delete version button in the toolbar (`data_contract.py:746`) uses the default secondary style. Apply a red/destructive color. Also applies to the Delete button inside `_delete_version_dialog` when deleting the latest version.

- **Suite picker legend** — `_suite_picker_dialog` in `data_contract_dialogs.py` shows colored left borders (green/amber/red) based on test status but provides no legend. Add a one-line caption explaining the color coding below the dialog intro text.

- **Term Read-Only Detail — styled code block** — `_term_read_dialog` in `data_contract_dialogs.py` uses `st.write()` to display the term value. Replace with `st.code()` for consistent monospace rendering, especially for YAML/SQL values.

### Partial — Needs Completion

- **"Staged Changes" label in Python** — The JS sticky bar and chip tooltips already use "Staged changes — not yet saved". The Python-side warning banner (`data_contract.py:764`) still reads "unsaved". Align the copy to match JS.

- **YAML tab — line numbers** — Guidance text and copy/download line-count feedback are done. Line numbers in the YAML viewer itself (`data_contract.js` `YamlViewer` / `pre.yaml-block`) are still missing.

- **Test Term Detail — 2-column max metadata** — The metadata row uses `st.columns(len(meta))` which expands to 4 columns when all fields (Status, Last Run, Dimension, Severity) are present. Cap at 2 columns per row to avoid awkward wrapping.

### Medium Effort

- **Collapsible pending edits bar** — The flat `st.warning()` summary string in the Python toolbar (`data_contract.py:764`) and the JS sticky bar truncate long edit lists. Replace with a collapsible `st.expander` (Python) / expand toggle (JS) showing each staged edit as its own line.

- **Dialog responsiveness** — Dialogs have no `@media (max-width: 600px)` breakpoints. Add narrow-screen CSS to `data_contract.js` to stack columns and reduce padding in the Governance Edit and Test Term Detail dialogs.

- **Health card "last updated" timestamps** — The CSS class `.health-card__run-time` exists but is never rendered. Wire up a "Last updated: X ago" timestamp below each health card metric; for the Anomalies card, note "Live data" to clarify it reflects current state rather than the snapshot.

---

## Appendix: YAML Import Test Cases

Exhaustive test cases for the YAML import path. These cover positive creates, updates, round-trips, and all failure/skip scenarios. These cases are the source of truth for `tests/unit/commands/test_odcs_contract.py`.

**Conventions:**
- `ERROR` — import aborts entirely; no rules processed
- `WARN` — this rule is skipped; import continues for other rules
- `SKIP` — rule silently ignored (no warning logged)

The current export format uses a flat rule structure: `id` (test UUID), `suiteId`, `type`, `metric`, `element` (table.column), and the operator as a key (`mustBe`, `mustBeLessOrEqualTo`, etc.). Creates omit `id`; after import the file is mutated in place with the new UUID.

---

### A1 — CREATE: New Tests from YAML (no `id` field)

#### A1.1 `nullValues` → `Missing_Pct` (percent, upper tolerance only)

```yaml
- name: email_null_pct
  type: library
  metric: nullValues
  mustBeLessOrEqualTo: 5.0
  unit: percent
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Fail
```

Expected: creates `Missing_Pct` test on `customers.email`, `threshold_value = "5.0"`, `test_operator = "<="`, severity `Fail`.

---

#### A1.2 `nullValues` → `Missing_Pct` (exact zero)

```yaml
- name: customer_id_null_zero
  type: library
  metric: nullValues
  mustBe: 0
  unit: percent
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Missing_Pct`, `threshold_value = "0"`, `test_operator = "="`.

---

#### A1.3 `nullValues` → `Missing_Pct` (range band)

```yaml
- name: phone_null_range
  type: library
  metric: nullValues
  mustBeBetween: [0.0, 10.0]
  unit: percent
  element: customers.phone
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Missing_Pct`, `lower_tolerance = "0.0"`, `upper_tolerance = "10.0"`.

---

#### A1.4 `nullValues` → `Missing_Pct` (greater-than threshold)

```yaml
- name: optional_field_has_some
  type: library
  metric: nullValues
  mustBeGreaterThan: 0
  unit: percent
  element: customers.middle_name
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Missing_Pct`, `threshold_value = "0"`, `test_operator = ">"`.

---

#### A1.5 `rowCount` → `Row_Ct` (minimum)

```yaml
- name: orders_min_rows
  type: library
  metric: rowCount
  mustBeGreaterOrEqualTo: 1000
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Row_Ct` table-level test, `threshold_value = "1000"`, `test_operator = ">="`.

---

#### A1.6 `rowCount` → `Row_Ct` (range band)

```yaml
- name: orders_row_range
  type: library
  metric: rowCount
  mustBeBetween: [1000, 100000]
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Row_Ct`, `lower_tolerance = "1000"`, `upper_tolerance = "100000"`.

---

#### A1.7 `rowCount` → `Row_Ct` (exact count)

```yaml
- name: config_table_exact_rows
  type: library
  metric: rowCount
  mustBe: 52
  unit: rows
  element: us_states
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Row_Ct`, `threshold_value = "52"`, `test_operator = "="`.

---

#### A1.8 `rowCount` → `Row_Ct` (less-than)

```yaml
- name: error_log_bounded
  type: library
  metric: rowCount
  mustBeLessThan: 500
  unit: rows
  element: error_log
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Row_Ct`, `threshold_value = "500"`, `test_operator = "<"`.

---

#### A1.9 `duplicateValues` → `Dupe_Rows` (exact zero, rows)

```yaml
- name: order_id_no_dups
  type: library
  metric: duplicateValues
  mustBe: 0
  unit: rows
  element: orders.order_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Dupe_Rows`, `threshold_value = "0"`, `test_operator = "="`.

---

#### A1.10 `duplicateValues` → `Dupe_Rows` (tolerance, rows)

```yaml
- name: product_sku_dup_tolerance
  type: library
  metric: duplicateValues
  mustBeLessOrEqualTo: 3
  unit: rows
  element: products.sku
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Dupe_Rows`, `threshold_value = "3"`, `test_operator = "<="`.

---

#### A1.11 `duplicateValues` → `Unique_Pct` (percent)

```yaml
- name: email_unique_pct
  type: library
  metric: duplicateValues
  mustBeGreaterOrEqualTo: 99.5
  unit: percent
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Unique_Pct`, `threshold_value = "99.5"`, `test_operator = ">="`.

---

#### A1.12 `invalidValues` + `arguments.pattern` → `Pattern_Match`

```yaml
- name: email_format_check
  type: library
  metric: invalidValues
  mustBe: 0
  unit: rows
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  arguments:
    pattern: '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
```

Expected: `Pattern_Match`, `threshold_value = "0"`, regex stored in pattern field.

---

#### A1.13 `invalidValues` + `arguments.pattern` + tolerance → `Pattern_Match`

```yaml
- name: zip_format_loose
  type: library
  metric: invalidValues
  mustBeLessOrEqualTo: 2.0
  unit: percent
  element: addresses.zip_code
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  arguments:
    pattern: '^\d{5}(-\d{4})?$'
```

Expected: `Pattern_Match`, `threshold_value = "2.0"`, `test_operator = "<="`.

---

#### A1.14 `invalidValues` + `arguments.validValues` → `LOV_Match`

```yaml
- name: status_valid_values
  type: library
  metric: invalidValues
  mustBe: 0
  unit: rows
  element: orders.status
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  arguments:
    validValues: [active, inactive, pending, cancelled]
```

Expected: `LOV_Match`, threshold `0`, valid values list stored.

---

#### A1.15 `invalidValues` + `arguments.validValues` + tolerance

```yaml
- name: country_code_mostly_valid
  type: library
  metric: invalidValues
  mustBeLessOrEqualTo: 5
  unit: rows
  element: addresses.country_code
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  arguments:
    validValues: [US, CA, GB, AU, DE, FR]
```

Expected: `LOV_Match`, `threshold_value = "5"`, `test_operator = "<="`.

---

#### A1.16 `sql` type → `CUSTOM`

```yaml
- name: recent_orders_exist
  type: sql
  query: "SELECT COUNT(*) FROM orders WHERE created_at > CURRENT_DATE - INTERVAL '7 days'"
  mustBeGreaterThan: 0
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `CUSTOM`, query stored in `custom_query`, `skip_errors = 0`.

---

#### A1.17 `sql` type with `mustBeLessOrEqualTo` (skip_errors semantics)

```yaml
- name: orphan_order_lines_check
  type: sql
  query: "SELECT COUNT(*) FROM order_lines ol LEFT JOIN orders o ON o.id = ol.order_id WHERE o.id IS NULL"
  mustBeLessOrEqualTo: 0
  unit: rows
  element: order_lines
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Fail
```

Expected: `CUSTOM`, `skip_errors = 0`, severity `Fail`.

---

#### A1.18 `custom/vendor:testgen` + `testType` → any TestGen type (round-trip restore)

```yaml
- name: amount_avg_shift
  type: custom
  vendor: testgen
  testType: Avg_Shift
  mustBeLessOrEqualTo: 10.0
  unit: rows
  element: orders.amount
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Warning
```

Expected: creates `Avg_Shift` test, `threshold_value = "10.0"`.

---

#### A1.19 `custom/vendor:testgen` + `testType: Schema_Drift`

```yaml
- name: orders_schema_stable
  type: custom
  vendor: testgen
  testType: Schema_Drift
  mustBeLessOrEqualTo: 0
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `Schema_Drift` monitor test.

---

#### A1.20 `custom/vendor:testgen` + `testType: Distribution_Shift`

```yaml
- name: amount_dist_shift
  type: custom
  vendor: testgen
  testType: Distribution_Shift
  mustBeLessOrEqualTo: 5.0
  unit: rows
  element: orders.amount
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

---

#### A1.21 Create with description and dimension fields

```yaml
- name: customer_id_completeness
  description: "All customer records must have a valid ID."
  type: library
  metric: nullValues
  mustBe: 0
  unit: percent
  element: customers.customer_id
  dimension: completeness
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Fail
```

Expected: description stored in `test_description`, dimension ignored on create (driven by test type).

---

#### A1.22 Create with no `suiteId` — defaults to first included suite

```yaml
- name: order_total_positive
  type: library
  metric: nullValues
  mustBe: 0
  unit: percent
  element: orders.total_amount
```

Expected: test created in first alphabetically-ordered included suite for the table group.

---

### A2 — UPDATE: Modify Existing Tests (rule has `id`)

#### A2.1 Update threshold value only

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111111"
  name: email_null_pct
  type: library
  metric: nullValues
  mustBeLessOrEqualTo: 3.0   # was 5.0
  unit: percent
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Fail
```

Expected: `threshold_value` updated to `"3.0"`, `last_manual_update` set, `lock_refresh = "Y"`.

---

#### A2.2 Update severity only

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111112"
  ...
  severity: Warning   # was Fail
```

Expected: only `severity` updated.

---

#### A2.3 Update test description (name field)

Expected: `test_description` updated.

---

#### A2.4 Update tolerance band (mustBeBetween)

```yaml
mustBeBetween: [2000, 200000]   # was [1000, 100000]
```

Expected: `lower_tolerance = "2000"`, `upper_tolerance = "200000"`.

---

#### A2.5 Update custom_query on CUSTOM test

```yaml
query: "SELECT COUNT(*) FROM orders WHERE created_at > CURRENT_DATE - INTERVAL '30 days'"   # was 7 days
```

Expected: `custom_query` updated.

---

#### A2.6 Update skip_errors on CUSTOM test

```yaml
mustBeLessOrEqualTo: 5   # was 0
```

Expected: `skip_errors = 5`.

---

#### A2.7 Multiple fields updated at once

Expected: both `threshold_value` and `severity` updated in one DB write.

---

#### A2.8 No-op update — nothing changed

Expected: no DB write; test appears in "no change" count in import report.

---

#### A2.9 Update CUSTOM test threshold (Avg_Shift)

Expected: `threshold_value = "5.0"`, `lock_refresh = "Y"`.

---

#### A2.10 Update — clear lower/upper tolerance by switching to single threshold

Behavior: if `mustBeBetween` is gone and a scalar operator is present, clear `lower_tolerance`/`upper_tolerance` and set `threshold_value`.

Expected: `lower_tolerance = NULL`, `upper_tolerance = NULL`, `threshold_value = "500"`.

---

### A3 — ROUND-TRIP Tests

| Case | Description | Expected |
|---|---|---|
| A3.1 | Export → import unchanged | `ContractDiff.total_changes == 0` |
| A3.2 | Export → change one threshold → import | Exactly one `test_updates` entry |
| A3.3 | Export → add new rule (no id) → import | New test created; id written back to YAML |
| A3.4 | Export → change contract version → import | `contract_updates["contract_version"]` updated |
| A3.5 | Export → remove a rule → import | No test deleted; orphan warning produced |
| A3.6 | Create → export → import back | Step 3 produces zero changes |
| A3.7 | Export → change severity → import → export | Step 3 shows 1 update; step 4 YAML reflects new severity |
| A3.8 | Round-trip preserves `suiteId` | Test stays in same suite |

---

### A4 — WRITE-BACK Behavior

| Case | Description |
|---|---|
| A4.1 | New test id written at correct YAML list position only |
| A4.2 | Multiple new tests — all ids written back |
| A4.3 | Mixed create + update — existing ids unchanged, new ids added |
| A4.4 | Write-back preserves YAML comments and formatting (ruamel.yaml) |
| A4.5 | Write-back is idempotent — importing twice does not duplicate ids |

---

### A5 — FUNDAMENTALS Updates

| Case | YAML field | Expected DB column |
|---|---|---|
| A5.1 | `version: "2.1.0"` | `contract_version = "2.1.0"` |
| A5.2 | `status: active` | `contract_status = "active"` |
| A5.3 | `description.purpose: "..."` | table group `description` updated |
| A5.4 | `domain: "commerce"` | `business_domain = "commerce"` |
| A5.5 | `dataProduct: "order-management"` | `data_product = "order-management"` |
| A5.6 | `slaProperties[latency].value: 4` | `profiling_delay_days = 4` |
| A5.7 | All of the above at once | Single UPDATE on `table_groups` |

---

### A6 — Failure Cases: Unsupported Metrics

**WARN** — `metric: missingValues` has no TestGen test type equivalent. TestGen checks SQL NULL only. Rule skipped.

---

### A7 — Failure Cases: Unsupported Operators

**WARN** — `mustNotBe` and `mustNotBeBetween` have no TestGen test_operator mapping. Rule skipped.

---

### A8 — Failure Cases: `invalidValues` Without Actionable Arguments

**WARN** for: no `arguments` block, empty `arguments`, `arguments.missingValues` only, `arguments.validValues` as empty list. Rule skipped.

---

### A9 — Failure Cases: Non-TestGen Custom Engines

**WARN** for: `engine: soda`, `engine: greatExpectations`, `engine: montecarlo`, `engine: dbt`. Rule skipped with message identifying the engine.

`type: custom, vendor: testgen` without `testType` → **WARN**. Unknown `testType` → **WARN**.

---

### A10 — `type: text` (No Operational Value)

**SKIP** (silent, no warning): documentation-only rules. No test created.

---

### A11 — Failure Cases: `sql` Type Problems

- No `query` field → **WARN**
- Empty `query` → **WARN**
- No threshold operator → **WARN**

---

### A12 — Failure Cases: Missing Required Fields

- No `type` → **WARN**
- `library` type with no or unrecognized `metric` → **WARN**
- No `element` (CREATE path) → **WARN**
- No threshold operator → **WARN**

---

### A13 — Failure Cases: Update Path Failures

- `id` not found in DB → **WARN**: may have been deleted
- `id` belongs to different table group → **WARN**
- Attempt to change `metric` (immutable) → **WARN**: remove `id` to create a new test
- Attempt to change `element` (immutable) → **WARN**: remove `id` to create a new test

---

### A14 — Failure Cases: Malformed Values

- Non-numeric threshold → **WARN**
- `mustBeBetween` is a scalar → **WARN**: must be `[low, high]`
- `mustBeBetween` array has wrong length → **WARN**
- `mustBeBetween` with non-numeric bounds → **WARN**
- `mustBeBetween` lower > upper → **WARN**
- Invalid `severity` value → **WARN** + partial success: severity falls back to `Fail`; rule still imports

---

### A15 — Document-Level Failures (abort entire import)

- YAML parse error → **ERROR**
- Wrong `apiVersion` (expected `v3.1.0`) → **ERROR**
- Wrong `kind` (expected `DataContract`) → **ERROR**
- Missing `id` field on document → **ERROR**
- Invalid `status` value → **ERROR**: must be `active`, `deprecated`, `draft`, `proposed`, or `retired`
- Table group not found → **ERROR**

---

### A16 — Suite Resolution Failures (CREATE path)

- `suiteId` not found in table group → **WARN**
- No `suiteId` and table group has no included suites → **WARN**

- `rowCount` with `unit: percent` (undefined semantics) → **WARN**: use `unit: rows`
