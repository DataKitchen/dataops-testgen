# Data Contract — Requirements & Implementation Reference

**Standard:** Open Data Contract Standard (ODCS) v3.1.0  
**Status:** Core feature complete; 196 unit tests passing

---

## Overview

TestGen generates, exports, and imports data contracts in ODCS v3.1.0 format. A data contract is a machine-readable YAML document — one per table group — that formally records every **term** TestGen can make about a dataset. "Term" is the canonical word throughout the codebase; an older term "claim" has been fully renamed.

The contract is a **saved snapshot**, not a live view. It captures schema, governance metadata, and active test suite definitions at a point in time and assigns a version number. The system then detects drift by comparing that snapshot against live data and prompts the user to review and re-save when things change.

Contracts flow in both directions:
- **Export:** TestGen generates a contract YAML from profiling data and test definitions.
- **Import:** A modified YAML can be uploaded to update thresholds, descriptions, and metadata.

The UI presents the contract as a full VanJS component page with a health grid, a Terms Detail view, a Coverage Matrix, a YAML viewer, and an upload panel.

---

## Why We Built This

Data consumers have no formal, machine-readable document that describes what a dataset looks like, what quality rules govern it, and who is responsible for it. TestGen already collects all the technical truth needed to produce such a document — profiling results, test definitions, test results, anomaly findings, schema metadata — but it had never been surfaced as a standard artifact.

The industry has converged on ODCS v3.1.0 (Bitol) as the target format for data contracts across data mesh and catalog ecosystems. TestGen's ODCS output can also feed the `data_contract` section of an ODPS v4.1 (Linux Foundation) data product document via the `odps-python` adapter (backlog).

A single table group maps to a single data contract. That table group can have many test suites. Each suite can be individually included or excluded from the contract via the `include_in_contract` flag, preventing operational or experimental suites from polluting the formal quality commitments.

---

## What It Does

### Three Layers of Coverage

**Layer 1 — Structural:** The DDL matches the contract. The right columns exist with the right types and lengths. Enforced by `Schema_Drift`, which detects column adds, drops, and type changes. New profile anomaly type `1001 · Suggested_Type` flags when observed data suggests a different column type than declared.

**Layer 2 — Value Compliance:** The data inside columns fits its declared type and size. Enforced by three new profile anomaly types:
- **1032 Exceeds_Declared_Length** — max observed length equals the declared `VARCHAR(N)` limit (silent truncation risk)
- **1033 Numeric_Precision_Overflow** — `NUMERIC(p,s)` column max value reaches `10^(p−s)` (overflow risk)
- **1034 Decimal_In_Integer_Column** — `INTEGER` column whose profiling suggests decimal values

**Layer 3 — Semantic Compliance:** The data means what the column name says. A column named `email` contains email addresses. Enforced by `functional_data_type` (40+ semantic types), `std_pattern_match` (EMAIL, PHONE_USA, ZIP_USA, SSN), and test types like `Email_Format`, `Valid_US_Zip`, `Pattern_Match`, `LOV_Match`.

### What TestGen Enforces vs. Cannot Enforce

**Enforces:** All quality rules (50+ test types), schema drift detection, value compliance anomaly detection (1032/1033/1034), semantic pattern validation, freshness and volume SLAs, referential integrity, custom SQL tests, DQ scoring per dimension.

**Detects but cannot prevent:** Structural DDL changes (`Schema_Drift` fires after the fact).

**Cannot enforce:** Legal terms and usage policy, pricing, access control / IAM roles, data retention, uptime SLA, query latency to consumers, column-level transformation lineage, team roster, escalation SLAs.

---

## Architecture & Key Files

### Python Backend

| File | Purpose |
|---|---|
| `testgen/commands/export_data_contract.py` | Full ODCS v3.1.0 YAML generator; 50+ test type mappings; respects `include_in_contract`; emits section-divider comments |
| `testgen/commands/import_data_contract.py` | ODCS import, diff preview, and apply engine; `lock_refresh = 'Y'` on imported thresholds |
| `testgen/commands/contract_versions.py` | `save_contract_version`, `load_contract_version`, `list_contract_versions`, `has_any_version`, `mark_contract_stale`, `mark_contract_not_stale` |
| `testgen/commands/contract_staleness.py` | `compute_staleness_diff` — computes `StaleDiff` (schema / quality / governance / suite scope diffs) between a saved YAML snapshot and current DB state |
| `testgen/ui/views/data_contract.py` | **Controller** (588 lines): `DataContractPage`, `_render_health_dashboard`, `_render_staleness_banner`, `_check_contract_prerequisites`, `_render_first_time_flow`; imports from all sub-modules; re-exports test-compat symbols |
| `testgen/ui/views/data_contract_props.py` | **Pure props/term builder** — no Streamlit, no DB calls; all shared constants (`_STATUS_ICON`, `_TIERS`, `_VERIF_META`, etc.); `_build_contract_props` (accepts `gov_by_col` to avoid internal DB round-trip); `_column_coverage_tiers`, `_tier_badge`, `_quality_counts`, `_worst_status`, `_extract_column_terms`, `_is_covered` |
| `testgen/ui/views/data_contract_yaml.py` | **Pure YAML/pending-edit helpers** — no Streamlit, no DB; `_delete_term_yaml_patch`, `_patch_yaml_governance`, `_apply_pending_governance_edit`, `_apply_pending_test_edit`, `_pending_edit_count` |
| `testgen/ui/queries/data_contract_queries.py` | **All DB query/write functions** — `_capture_yaml`, `_fetch_anomalies`, `_fetch_suite_scope`, `_fetch_governance_data`, `_lookup_column_id`, `_fetch_test_live_info`, `_fetch_test_statuses`, `_fetch_last_run_dates`, `_save_governance_data`, `_persist_governance_deletion`; all decorated `@with_database_session` |
| `testgen/ui/views/dialogs/data_contract_dialogs.py` | **All `@st.dialog` functions** — `_governance_edit_dialog`, `_suite_picker_dialog`, `_monitor_term_dialog`, `_test_term_dialog`, `_term_read_dialog`, `_term_edit_dialog`, `_edit_rule_dialog`, `_regenerate_dialog`, `_save_version_dialog`, `_review_changes_panel`; also `_modal_header`, `_render_live_terms_row` |
| `testgen/ui/views/test_suites.py` | "Data Contract" button in actionContent; "Include in Data Contract" checkbox in Edit dialog; `mark_contract_stale` hook |
| `testgen/ui/bootstrap.py` | `DataContractPage` registered in `BUILTIN_PAGES` |
| `testgen/ui/components/widgets/testgen_component.py` | `"data_contract"` in `AvailablePages` literal |
| `testgen/__main__.py` | CLI: `testgen export-data-contract` and `testgen import-data-contract` |
| `testgen/common/models/table_group.py` | ORM: `contract_stale`, `last_contract_save_date` (active); `contract_version`, `contract_status` (deprecated columns, left in DB) |
| `testgen/common/models/test_suite.py` | ORM: `include_in_contract` |

**Module dependency order** (no circular imports): `data_contract_queries` → `data_contract_yaml` → `data_contract_props` → `data_contract_dialogs` → `data_contract`

### JavaScript Frontend

| File | Purpose |
|---|---|
| `testgen/ui/components/frontend/js/pages/data_contract.js` | **VanJS page** — PageHeader, HealthGrid, TabBar, TermsDetail, CoverageMatrix, TermCountsBar, YAML viewer, Upload tab; all rendering and tab switching client-side |
| `testgen/ui/components/frontend/js/main.js` | `data_contract` loader registered |
| `testgen/ui/components/frontend/js/pages/test_suites.js` | "Data Contract" button per suite card |
| `testgen/ui/components/frontend/js/pages/project_dashboard.js` | "Data Contract" link per table group card |
| `testgen/ui/components/frontend/js/pages/table_group_list.js` | "View Data Contract" link per table group card |

### Migrations

| Migration | Purpose |
|---|---|
| `testgen/template/dbupgrade/0180_incremental_upgrade.sql` | Adds `contract_version` (VARCHAR, deprecated), `contract_status` (VARCHAR, deprecated) to `table_groups` |
| `testgen/template/dbupgrade/0181_incremental_upgrade.sql` | Adds profile anomaly types 1032, 1033, 1034 (value compliance term risk detection) |
| `testgen/template/dbupgrade/0182_incremental_upgrade.sql` | Idempotent `IF NOT EXISTS` safety re-apply for contract columns |
| `testgen/template/dbupgrade/0183_incremental_upgrade.sql` | Adds `include_in_contract BOOLEAN NOT NULL DEFAULT TRUE` to `test_suites` |
| `testgen/template/dbupgrade/0184_incremental_upgrade.sql` | Adds `data_contracts` table (versioned snapshots) + `contract_stale`, `last_contract_save_date` columns to `table_groups` |

### Tests

| File | Count | Covers |
|---|---|---|
| `tests/unit/commands/test_data_contract_export.py` | 91 | Export mapping, anomaly criteria, YAML output |
| `tests/unit/commands/test_data_contract_import.py` | 41 | Import validation, diff, apply, round-trip |
| `tests/unit/ui/test_data_contract_page.py` | 39 | Page registration, coverage tiers, JS link hrefs, `Test_TermCountConsistency` |
| `tests/unit/ui/test_contract_pending_edits.py` | 18 | Pending edit accumulation, YAML patching, persistence helpers |
| `tests/unit/commands/test_contract_staleness.py` | Started | `compute_staleness_diff` — governance diff; schema/quality/scope diffs in progress |

---

## DB Schema

### `data_contracts` table (migration 0184)

The primary storage for versioned contract snapshots.

```sql
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
```

Version numbers are integers starting at 0, auto-incremented using a single atomic `INSERT ... SELECT MAX(version)+1` — no separate SELECT/INSERT race condition. The `UNIQUE` constraint is a safety net.

### `table_groups` additions (migrations 0180 + 0184)

| Column | Type | Default | Status |
|---|---|---|---|
| `contract_stale` | BOOLEAN | FALSE | Active — set TRUE when profiling runs or tests change after last save |
| `last_contract_save_date` | TIMESTAMPTZ | NULL | Active — updated on each `save_contract_version` call |
| `contract_version` | VARCHAR(20) | NULL | **Deprecated** — superseded by `data_contracts.version`; left in DB to avoid breaking rows |
| `contract_status` | VARCHAR(20) | 'draft' | **Deprecated** — the versioned model has no lifecycle state machine; left in DB |

### `test_suites` addition (migration 0183)

| Column | Type | Default | Purpose |
|---|---|---|---|
| `include_in_contract` | BOOLEAN NOT NULL | TRUE | Controls whether this suite's test definitions are exported as quality rules |

Default TRUE means all existing and newly created suites are automatically included; no action required for standard deployments. Monitor suites (`is_monitor = TRUE`) are always excluded regardless of this flag.

### `profile_anomaly_types` additions (migration 0181)

| ID | Anomaly Type | Dimension | Trigger |
|---|---|---|---|
| 1032 | Exceeds_Declared_Length | Validity | `max_length >= declared VARCHAR(N)` |
| 1033 | Numeric_Precision_Overflow | Accuracy | `max_value >= 10^(p−s)` for `NUMERIC(p,s)` |
| 1034 | Decimal_In_Integer_Column | Validity | INTEGER column with `datatype_suggestion` suggesting NUMERIC |

Anomaly findings are UI-only (fetched from `profile_anomaly_results` at render time). They are not exported to the contract YAML and not modifiable via import.

---

## YAML Format

### Fundamentals

```yaml
apiVersion: v3.1.0
kind: DataContract
id: <table_groups.id>           # UUID — read-only on import
version: <integer>              # from data_contracts.version
name: <table_groups_name>
tenant: <project_code>
domain: <business_domain>       # importable
dataProduct: <data_product>     # importable
tags: [<data_source>, <transform_level>]
description:
  purpose: <table_groups.description>  # importable
```

### Schema (DDL + Profiling terms — read-only on import)

Each table in `data_column_chars` becomes an object entry; each column becomes a property. Key mappings:

- `physicalType` ← `db_data_type`
- `logicalType` ← `functional_data_type` (40+ types → 7 ODCS types)
- `required: true` ← `null_value_ct == 0`
- `criticalDataElement` ← `data_column_chars.critical_data_element`
- `classification` ← `pii_flag` risk prefix: A → confidential, B → restricted, C (or any truthy) → public
- `logicalTypeOptions.primaryKey: true` ← `functional_data_type = 'ID-Unique'` or all values unique + not-null
- `logicalTypeOptions.{minLength, maxLength, minimum, maximum}` ← profiling stats
- `logicalTypeOptions.format` ← `std_pattern_match` (email, zip-us, phone-us, ssn-us)
- `examples` ← `top_freq_values` from profiling
- `description` ← `data_column_chars.description`

PII model is binary in the UI: any truthy `pii_flag` = PII. Stored as `"MANUAL"` when set, `NULL` when cleared.

### References (foreign keys — read-only on import)

`Combo_Match` test definitions map to ODCS `references` as foreign key entries.

### Quality (test terms — partially importable)

Each active `test_definition` in suites where `include_in_contract = TRUE` becomes one ODCS quality rule.

**Test type → ODCS type mapping:**
- `CUSTOM` → `type: sql`
- `Missing_Pct`, `Row_Ct`, `Dupe_Rows`, `Email_Format`, `Valid_US_Zip`, `LOV_Match` → `type: library`
- All others → `type: custom, vendor: testgen`

**DQ dimension → ODCS dimension mapping:**

| TestGen | ODCS |
|---|---|
| Validity | `conformity` |
| Completeness | `completeness` |
| Accuracy | `accuracy` |
| Coverage | `coverage` |
| Freshness / Timeliness | `timeliness` |
| Uniqueness | `uniqueness` |
| Consistency | `consistency` |

Importable quality rule fields: `name`, `severity`, threshold operator/value, `mustBeBetween` tolerances, `query` (CUSTOM tests only), `mustBeLessOrEqualTo` (CUSTOM `skip_errors`). Importing a threshold sets `lock_refresh = 'Y'` to protect it from auto-generation.

### SLA

- `latency` ← `profiling_delay_days` (importable)
- `errorRate` ← `1 - dq_score_test_run` (read-only)

### Servers

All 8 TestGen database flavors map to ODCS server types: PostgreSQL, Snowflake, BigQuery, SQLServer, Redshift, Databricks, Trino, Oracle. Read-only on import.

### `x-testgen` Extension Block

When any suites are included or excluded, a non-standard extension block appears at the YAML root:

```yaml
x-testgen:
  includedSuites:
    - orders_suite
    - billing_suite
  excludedSuites:
    - experimental_suite
```

Per the ODCS specification, `x-` prefixed keys are reserved for vendor extensions and ignored by standard ODCS tooling. The block is emitted even when all suites are included (with `excludedSuites: []`).

### `testRunHistory` (non-standard extension)

The last 5 completed test runs across all suites, with `executedAt`, `suite`, `testCount`, `passed`, `failed`, `warning`, `dqScore`. Read-only on import.

### `compliance` (non-standard extension)

Overall pass/fail status by DQ dimension plus violated tests from the last run. Read-only on import — edits in an uploaded YAML are silently discarded.

### `customProperties`

Fields with no ODCS home: `sourceSystem`, `sourceProcess`, `dataLocation`, `transformLevel`, `exportedAt`.

---

## UI Patterns & Constraints

### Architecture: Full VanJS Component

The Data Contract page is a **single VanJS component** (`data_contract.js`). Python's `render()` pre-computes all display data in `_build_contract_props()` and passes it as JSON props via `testgen_component("data_contract", props)`. All rendering, tab switching, and filtering happen client-side. There are no Streamlit widgets in the main display area.

Page key: `data-contract`. Navigation: `?table_group_id=<uuid>`, `?version=<N>` for historic versions.

Access points: Table Groups page → "View Data Contract"; Test Suites page → "Data Contract" button; Project Dashboard → "Data Contract" inline with DQ score; direct URL.

### Modal Architecture (Critical Constraint)

The VanJS component iframe **clips `position: fixed/absolute` elements**. ALL modals must go through:

```
JS: emitEvent("TermDetailClicked", { term, tableName, colName })
  → Python event_handlers["TermDetailClicked"]
  → @st.dialog renders
```

Do NOT use VanJS popups or positioned overlays inside the component iframe.

Use `event_handlers` (not `on_change_handlers`) for any handler that calls `st.rerun()`.

### Events (JS → Python)

All four live events go through `event_handlers` (supports `st.rerun()`):

| Event | Payload | Handler |
|---|---|---|
| `EditRuleClicked` | `{ rule_id }` | Open `@st.dialog` for test term edit |
| `TermDetailClicked` | `{ term, tableName, colName }` | Open `@st.dialog` for governance or read-only term view |
| `SuitePickerClicked` | — | Open `@st.dialog` suite picker (include/exclude suites) |
| `GovernanceEditClicked` | `{ tableName, colName }` | Open `@st.dialog` for governance term edit |

The Upload tab handles import inline (no JS event): Python reads uploaded YAML via `st.file_uploader`, calls `run_import_data_contract`, and displays the diff result. Version navigation is handled via `st.query_params["version"]` with `safe_rerun()` — no JS event needed.

### Per-Column Props Shape

```json
{
  "name": "customer_email",
  "type": "varchar(255)",
  "is_pk": false,
  "is_fk": false,
  "covered": true,
  "status": "passing",
  "static_terms": [
    { "name": "varchar(255)", "value": "...", "source": "ddl", "verif": "db_enforced" },
    { "name": "email",        "value": "...", "source": "governance", "verif": "declared" }
  ],
  "live_terms": [
    { "name": "Email Format", "source": "test", "verif": "tested", "status": "passing", "rule_id": "..." }
  ]
}
```

### Page Header

Table group name · version number · meta pills (domain, data product, server type, schema path) · description text below title.

Action buttons (Streamlit row, full-width):
- **Refresh** — reload saved contract from DB; clears pending in-memory edits (with confirmation if edits exist).
- **Save version** — secondary style when no edits pending; primary style with label `Save ● (N)` when N edits are staged.

The **Download YAML** button lives in the YAML tab toolbar (next to Copy), not in the page header. It uses the browser `Blob` / `URL.createObjectURL` API — no server round-trip.

### Staleness Banner

When `contract_stale = TRUE`, a dismissible banner appears below the header showing what changed since the last save. "Review Changes" opens a diff panel; save is only available inside the panel (after the user has seen what changed). Dismiss hides the banner for the session only (`dc_stale_dismissed:{tg_id}` session key).

### Health Grid (always visible, above tabs)

Three animated metric cards:

- **Coverage** — % columns with ≥1 non-schema term; progress bar; "View N uncovered →" cross-filters Terms Detail. A column is **covered** when it has at least one of: `classification`, `criticalDataElement`, `description`, `logicalTypeOptions.format`, or a quality rule. Canonical definition: `data_contract.py::_is_covered()`. Color thresholds: green ≥ 80%, orange ≥ 50%, red < 50%.
- **Test Health** — proportional summary bar (passing / warning / failing / not run); count breakdown; "View N failures →" cross-filter; when suites are excluded shows "From N of M suites" sub-note.
- **Hygiene** — definite / likely / possible anomaly counts from latest profiling run; "View N anomalies →" cross-filter. Always shows **live** data even when viewing a historic contract version; caption reads "Anomalies are always current — not from this snapshot."

### Tab Bar (client-side, no rerun)

**Contract Terms** · **Coverage Matrix** · **YAML** · **Upload Changes**

(Gap Analysis was previously a separate tab; it is now a summary card within the Contract Terms tab.)

### Contract Terms — Terms Detail

- Section header: "? What is a contract term?" button opens a modal explaining all four sources and five verification levels.
- Table sections: 20px bold name + column count + N table-level terms.
- Column rows: 2-col grid (240px header | terms).
  - Header: column name 17px monospace · type · PK/FK badges.
  - Terms chips color-coded by source: DDL (purple) · Profiling (blue) · Governance (gold/amber) · Test (green).
  - Verification badge per chip: 🏛️ DB Enforced · ⚡ Tested · 📡 Monitored · 📸 Observed · 🏷️ Declared.
  - Live test chips show last-run status pill; inline **Edit** → `EditRuleClicked` → Python `@st.dialog`.
- **Table-level terms**: tests or annotations that apply to the whole table (row count, freshness, referential integrity) appear in a "(table-level)" sub-section above column rows within each table block.
- Filter buttons: **All** · **Failing** · **Uncovered** (plus per-verification-tier filters). Filtering strips non-matching terms from within each column — a column with no matching terms is hidden entirely. Health card filter buttons share state with these filters.
- Collapsed accordion header (`ts-name` / `ts-meta` CSS pattern): table name left, counts right.

### Coverage Matrix Tab

HTML `<table>` with one row per column across all tables plus a `(table-level)` row when table-level rules exist. The **TermCountsBar** sits at the top showing total term counts by source (DDL / Profiling / Governance / Test) and by verification tier.

Five tier columns:

| Column | Badge | What counts |
|---|---|---|
| DB Enforced 🏛️ | Physical type (always 1 per column) |
| Tested ⚡ | Non-monitor active test definitions |
| Monitored 📡 | `Freshness_Trend`, `Volume_Trend`, `Schema_Drift`, `Metric_Trend` only |
| Observed 📸 | Profiling stats: min/max, row count, uniqueness, format pattern, logical type |
| Declared 🏷️ | Governance annotations: classification, CDE flag, description |

**Term count consistency invariant**: the grand total in the Coverage Matrix must equal the TermCountsBar total by source and by tier, both of which must equal the total in the Terms Detail accordion header. Enforced by `Test_TermCountConsistency` unit tests.

"Monitored" means exactly `_MONITOR_TEST_TYPES = {"Freshness_Trend", "Volume_Trend", "Schema_Drift", "Metric_Trend"}`. Profiling anomaly results are sourced as `profiling` / `observed`, not monitored.

### Modal Header Design

All five term/governance dialogs share `_modal_header(verif, name, table_name, col_name, subtitle="")`:
- **Line 1 (bold, 17px):** `{icon} {verif_label} — {name}` (e.g. `⚡ Tested — Null Check`)
- **Line 2 (caption, monospace):** `table_name · col_name`
- **Optional subtitle:** test type description below the divider

### Pending Edit Model

Term edits are held in Streamlit session state until the user explicitly saves a new version. Two keys must stay in sync:

- `dc_yaml:{table_group_id}` — the in-memory YAML doc, patched on each edit. Rendering source of truth.
- `dc_pending:{table_group_id}` — list of pending edits. Drives the dirty button and save dialog summary.

Every "Apply" click must patch both keys before `safe_rerun()`. `dc_yaml` must never be reloaded from DB while `dc_pending` is non-empty.

On version save:
1. Write governance pending edits → `data_column_chars`
2. Write test pending edits → `test_definitions`
3. Build snapshot YAML from the current **in-memory patched doc** — NOT from a fresh export (a fresh export would pull in new anomalies or test results that occurred after the user started editing)
4. Call `save_contract_version(table_group_id, snapshot_yaml, label)`
5. Clear both session keys; next render loads the newly saved version from DB

Navigating away with unsaved changes shows a confirmation dialog ("Leave without saving? N unsaved changes will be lost").

### Historic Version Read-Only Mode

When viewing a non-latest version (selected via version picker dropdown in header):
- Blue "historical version" banner pinned below the header with "View Latest →" link.
- Coverage and test health cards reflect the **snapshot** at that version.
- Hygiene card shows **live** anomalies with caption.
- All edit chip buttons disabled; tooltip: "Switch to the latest version to make edits."
- Refresh button and Save button disabled.
- Download YAML produces the historic snapshot verbatim.

---

## Implementation Notes

### Shared Utilities

`_pii_flag_to_classification(pii_flag: str) -> str` lives in `export_data_contract.py` and is imported by `contract_staleness.py`. Do not duplicate this mapping.

### HTML Escaping

All user-sourced strings rendered inside term cards (descriptions, classification values, test threshold expressions) must use `html.escape(value, quote=True)`. Never use manual `.replace("<", "&lt;")` chains — they miss `&`, `"`, and `'`.

### SQL Safety

Never f-string-interpolate UUIDs or user-supplied values into SQL. Use parameterized queries (`%s` placeholders with a parameters tuple). This applies to `_fetch_anomalies` and all other query helpers in `data_contract_queries.py`.

Use `CAST(:x AS uuid)` — never `::uuid` — in SQLAlchemy queries (conflicts with `:param` binding syntax).

### Logging

Use `LOG = logging.getLogger(__name__)` consistently throughout all data contract modules. Do not mix `LOG` and `_log`. Silent exception swallowing (`bare except: pass`) must log at `WARNING` level with `exc_info=True` before returning.

### What Is Stored in a Saved Contract

The snapshot captures: schema (column names, physical types, nullability, PK/FK, observed stats), governance (classification, CDE flags, descriptions), quality rules (test definitions with thresholds and operators), references (foreign key relationships), SLA (declared latency), and suite scope (which suites were included at save time).

The snapshot does **not** capture:
- Test results (`lastResult`) — always fetched fresh from `test_results`
- Compliance summary — computed at render time from live results
- Test run history — fetched fresh from `test_runs`
- Profiling anomalies — fetched fresh from `profile_anomaly_results`

This means the same saved contract snapshot shows different live health depending on when it is viewed — this is intentional behavior.

### Staleness Detection Triggers

`contract_stale` is set to TRUE when:
- A profiling run completes with `profiling_starttime > last_contract_save_date`
- Any `test_definitions` row for the table group is inserted, updated, or deleted
- Any `test_suites.include_in_contract` is toggled for the table group

Schema drift (columns added or dropped in the source database) is surfaced via the profiling run trigger; there is no DDL-watch mechanism (future enhancement).

Staleness is a warning, not a lock. The saved contract remains viewable and downloadable.

### `mark_contract_stale` Scope Note

`mark_contract_stale` only sets `contract_stale = TRUE` if `last_contract_save_date IS NOT NULL` — a table group with no saved contract cannot be stale.

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
```

Both commands automatically respect the `include_in_contract` flag — no additional arguments required.

Python API:
```python
from testgen.commands.import_data_contract import run_import_data_contract

diff = run_import_data_contract(yaml_content, table_group_id, dry_run=True)
print(diff.summary())

diff = run_import_data_contract(yaml_content, table_group_id, dry_run=False)
```

### Import Validation Rules

| Rule | Behavior |
|---|---|
| `apiVersion` must be `v3.1.0` | Error — blocks import |
| `kind` must be `DataContract` | Error — blocks import |
| `id` must be present | Error — blocks import |
| `status` must be in valid set | Error — blocks import |
| Invalid YAML syntax | Error — blocks import |
| Unknown test definition `id` | Warning — skipped |
| `latency` unit must be `day` or `d` | Warning if invalid — skipped |
| Non-CUSTOM test with `query` field | Ignored silently |

Import only applies quality-rule changes to suites with `include_in_contract = TRUE`. Changes targeting excluded suites are silently skipped.

---

## Current Status

### Complete

| Component | Detail |
|---|---|
| Database migrations (0180–0184) | All schema in place; `data_contracts` versioned snapshot table; staleness columns; anomaly types 1032/1033/1034 |
| Export engine | 669-line ODCS v3.1.0 generator; all 50+ test type mappings; `include_in_contract` filter |
| Import / round-trip | Validation, diff preview, apply; `lock_refresh` on imported thresholds; excluded suites skipped |
| CLI | `export-data-contract` and `import-data-contract` |
| VanJS UI page | Health grid, Contract Scope chip bar, Terms Detail, Coverage Matrix with TermCountsBar, YAML viewer, Upload tab |
| UI navigation | Links from Test Suites, Project Dashboard, Table Groups pages |
| Suite edit dialog | "Include in Data Contract" checkbox |
| Contract version data layer | `contract_versions.py` — save, load, list, `has_any_version` |
| Staleness detection hooks | `mark_contract_stale` wired into profiling and test definition changes |
| Staleness diff computation | `contract_staleness.py` — `StaleDiff` dataclass; SQL column bugs fixed; composite FK ref matching |
| Pending edit model | `dc_pending:{tg_id}` session state; YAML patched on edit; flushed to DB on version save |
| Page load from saved snapshot | `render()` loads from `load_contract_version`; first-time flow via `has_any_version` gate |
| First-time flow | Prerequisites check → Generate Contract Preview → Save as v0 |
| Staleness banner + diff panel | `_render_staleness_banner`, `_review_changes_panel` dialog |
| Version picker + historic view | Selectbox version picker; historic read-only banner; `?version=N` query param |
| Old lifecycle artifacts removed | `_STATUS_COLOR` removed; old `contract_version`/`contract_status` writes removed from active code |
| Frontend updates | Version display, staleness indicator, pending count badge, historic read-only mode |
| Unit tests (export, import, page) | 196 tests total (91 export, 41 import, 39 UI, 25 staleness) — all passing |

### Backlog / Partial

| Item | Priority | Notes |
|---|---|---|
| Remaining unit tests (phases 5/7/8/9) | Medium | `test_contract_pending_edits.py`, `test_contract_first_time_flow.py`, `test_contract_staleness_ui.py`, `test_contract_historic_view.py` |
| Staleness hooks — test definition changes | Medium | `mark_contract_stale` not yet called from all test definition write paths |
| YAML `dimension` field on quality rules | Low | Already mapped via `_DQ_DIMENSION_MAP`; verify rendering in downstream tools |
| `Column_Schema_Assert` test type | Medium | Per-column DDL assertion complementing table-group-level `Schema_Drift` |
| ODPS v4.1 adapter | Low | Wrap ODCS output inside `OpenDataProduct` envelope for data product catalog publishing |
| Contract version history page | Low | YAML snapshot diff viewer across versions; currently only the latest snapshot is shown by default |

---

## Relationship to External Standards

| Standard | Role |
|---|---|
| **ODCS v3.1.0** (Bitol) | Target output format — the contract document itself |
| **ODPS v4.1** (Linux Foundation) | Broader data product spec; TestGen's ODCS output feeds the `data_contract` section of an ODPS document |
| **DataContract Specification** | Deprecated predecessor to ODCS — not implemented |

### What Requires Human Input to Complete a Full Contract

These ODCS sections require a data catalog or governance form — TestGen cannot generate them from data alone:

`description.limitations`, `description.usage`, `team.members` (roster, roles, tenure), `roles` (IAM permissions), `support` (Slack/Teams channels), `price`, `authoritativeDefinitions`, column-level `businessName`.
