# Data Contract — Product Requirements Document

**Feature branch:** `data-contracts-vibe`
**Standard:** ODCS v3.1.0
**Last updated:** 2026-04-09

---

## Overview

The Data Contract feature surfaces TestGen test suites as a formal, exportable data contract mapped to ODCS v3.1.0 YAML. It provides a health dashboard, a coverage matrix, inline term editing, YAML import/export, and bulk term deletion.

**Page entry point:** `?table_group_id=<uuid>` on page key `data-contract`

---

## Architecture

| Layer | File | Role |
|---|---|---|
| View | `testgen/ui/views/data_contract.py` | Page render, event handlers |
| Frontend | `testgen/ui/components/frontend/js/pages/data_contract.js` | VanJS UI, selection mode, modals via `emitEvent` |
| Props | `testgen/ui/views/data_contract_props.py` | Props builder, `_classify_enforcement_tier`, coverage tiers |
| YAML helpers | `testgen/ui/views/data_contract_yaml.py` | Mutation helpers, `_delete_term_yaml_patch` |
| DB queries | `testgen/ui/queries/data_contract_queries.py` | `_fetch_test_statuses`, `_persist_governance_deletion`, `_GOVERNANCE_LABEL_TO_FIELD` |
| Export | `testgen/commands/export_data_contract.py` | ODCS YAML generation |
| Import | `testgen/commands/odcs_contract.py` | `run_import_contract`, `get_updated_yaml`, `ContractDiff` |
| Staleness | `testgen/commands/contract_staleness.py` | `compute_staleness_diff`, `compute_term_diff` (in progress) |
| Versions | `testgen/commands/contract_versions.py` | Save/load contract version snapshots |

**Modal pattern:** ALL modals use `emitEvent` → Python `event_handlers` → `@st.dialog`. No VanJS overlays inside the component iframe (iframes clip `position: fixed/absolute`).

---

## Features

### 1. Health Dashboard — **Implemented**

Three top cards on every page load:

- **Coverage** — percent of schema columns with at least one non-schema quality term; filter link to uncovered columns.
- **Test Health** — pass/warn/fail/not-run counts for quality tests in the contract YAML.
- **Hygiene** — Definite/Likely/Possible profiling anomaly counts; filter link to anomalous columns.

Test statuses are fetched fresh from DB via `_fetch_test_statuses()` on each render. The cached YAML `lastResult` is not used.

---

### 2. Coverage Matrix (Contract Claim Completeness) — **Implemented**

Term grid across all schema columns, organized by enforcement tier:

- `db` — DDL-type terms (data type, not-null, primary key)
- `unf` — observed/undeclared terms (sourced from profiling, not yet asserted)
- `tg` — TestGen-enforced (test and monitor suite definitions)

Tier classification: `testgen/ui/views/data_contract_props.py:_classify_enforcement_tier`

---

### 3. YAML Export (Download) — **Implemented**

Exports a full ODCS v3.1.0 YAML document covering:

- `fundamentals` — version, status, domain, dataProduct, description, slaProperties
- `schema` — columns with physicalType, logicalType, constraints, logicalTypeOptions (min/max/format/etc.), governance fields (CDE, PII, description)
- `quality` — one rule per test definition with operator, threshold, tolerance, severity, suiteId
- `servers`, `references`, `compliance` sections

**Entry point:** `testgen/commands/export_data_contract.py`
The frontend triggers a browser download (`a.download`) directly from the YAML string in props — no `emitEvent` round-trip needed for the download itself.

**Known limitations:**
- Schema section is read-only on import (TestGen is source of truth for column types/classification).
- `servers` and `references` are also read-only on import.

---

### 4. YAML Import (Upload) — **Implemented**

Accepts an ODCS v3.1.0 YAML file and applies changes back to TestGen:

**Supported mutations:**
- Create new tests (rules without `id`) → new UUID written back to YAML
- Update existing tests (rules with `id`) — threshold, tolerance, severity, description, custom_query
- Update contract fundamentals — version, status, description.purpose, domain, dataProduct, slaProperties.latency

**Entry points:**
- `testgen/commands/odcs_contract.py:run_import_contract` — validates and applies
- `testgen/commands/odcs_contract.py:get_updated_yaml` — writes new UUIDs back into the uploaded YAML for display
- `testgen/ui/views/data_contract.py:on_import_contract` — event handler, busts YAML/anomaly/version caches on success

**Event flow:** JS `emitEvent('ImportContractClicked', { payload: fileContent })` → Python `on_import_contract` → `run_import_contract` → result stored in `st.session_state[import_key]` → `safe_rerun()` → banner rendered.

**Result object:** `ContractDiff` — `.test_inserts`, `.test_updates`, `.contract_updates`, `.table_group_updates`, `.warnings`, `.errors`, `.has_errors`, `.total_changes`

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
- Missing `type`, missing `metric`, missing `element`, missing threshold
- `id` not found in DB or belongs to different table group
- Attempt to change `metric` or `element` on an existing test (immutable)

**Test coverage:** `docs/contract_import_positive_cases.md` (38 cases across create/update/round-trip/write-back/fundamentals), `docs/contract_import_failure_cases.md` (35 failure/skip cases).

**Known gaps:**
- Deleting a test via YAML (omitting a rule that exists in DB) is intentionally not supported — produces an orphan warning, not a delete.
- Metric-type changes on existing tests require delete + re-create.

---

### 5. Bulk Multi-Select Delete — **Implemented**

Allows users to select and delete multiple contract terms at once.

**User flow:**
1. Click **Select** button in the terms toolbar → enters selection mode (`_selectionMode.val = true`)
2. Checkboxes appear on all term chips
3. Click individual chips to toggle selection; a running count appears in the toolbar
4. Click **Delete contract terms** → shows "Are you sure?" confirmation prompt
5. Click **Yes, delete** → `confirmDelete()` → `emitEvent('BulkDeleteTermsClicked', { terms: [...] })` → Python `on_bulk_delete_terms`

**What gets deleted by term source:**

| Source | Action |
|---|---|
| `test` / `monitor` | Rule removed from `quality` array in YAML by `rule_id` |
| `ddl` | Field (`physicalType`, `required`, `_logicalTypeOptions.primaryKey`) removed from `schema[].properties[]` |
| `profiling` | `logicalTypeOptions` subfield (`minimum`, `maximum`, `minLength`, `maxLength`, `format`, `logicalType`) removed from `schema[].properties[]` |
| `governance` | `criticalDataElement` or `description` removed from YAML **and** DB column in `data_column_chars` reset via `_persist_governance_deletion` |

**Atomicity:** Governance DB writes happen before YAML is committed to `st.session_state`. If any DB write fails, YAML is not updated and an error banner is shown.

**Key files:**
- `testgen/ui/components/frontend/js/pages/data_contract.js` — `enterSelectionMode`, `exitSelectionMode`, `confirmDelete`, `BulkDeleteTermsClicked`
- `testgen/ui/views/data_contract.py:on_bulk_delete_terms` — handler (steps 1–4 above)
- `testgen/ui/views/data_contract_yaml.py:_delete_term_yaml_patch` — YAML field removal for DDL/profiling/governance terms
- `testgen/ui/queries/data_contract_queries.py:_persist_governance_deletion` — DB write for governance deletions
- `testgen/ui/queries/data_contract_queries.py:_GOVERNANCE_LABEL_TO_FIELD` — label → (db_column, reset_value) map with allowlist enforcement

**Tests:** `tests/unit/ui/test_bulk_delete_terms.py` — 20 unit tests covering:
- `_GOVERNANCE_LABEL_TO_FIELD` completeness and allowlist safety
- `_persist_governance_deletion` guard conditions (empty col, unknown term, allowlist)
- YAML mutation for all term sources (test, DDL, profiling, governance)
- Partial-failure safety: governance DB failure must not corrupt YAML session state

**Known limitations:**
- Table-level governance terms (not column-scoped) are not deletable — `_persist_governance_deletion` requires a non-empty `col_name`.
- PII term editing/deletion requires `view_pii` permission to render the chip in the first place.
- Governance terms are sourced from `data_column_chars` DB, not YAML — deletions must always write to DB, not just YAML.

---

### 6. Contract Term Differences — **In Progress**

Design spec: `docs/superpowers/specs/2026-04-08-data-contract-differences-design.md`
Implementation plan: `docs/superpowers/plans/2026-04-08-contract-term-differences.md`

Replaces cards 2 & 3 in the health dashboard and adds two new tabs:

- **Contract Term Differences** tab — four accordions (Changed / New / Deleted / Same) comparing saved YAML against current TestGen state
- **Contract Term Compliance** tab — term-by-term drill-down of enforcement tier pass/fail status

**Status of tasks:**
- Task 1 (`compute_term_diff` data structures in `contract_staleness.py`) — complete
- Task 2 (wire into `data_contract.py` props) — in progress
- Tasks 3–5 (frontend cards, differences tab, compliance tab) — pending

---

## DB Schema

| Column | Table | Type | Purpose |
|---|---|---|---|
| `include_in_contract` | `test_suites` | `BOOLEAN NOT NULL DEFAULT TRUE` | Controls which suites are in scope for the contract |
| `is_monitor` | `test_suites` | `BOOLEAN` | Monitor suites — excluded from contract test counts and suite picker |

Migration: `testgen/template/dbupgrade/0183_incremental_upgrade.sql`
