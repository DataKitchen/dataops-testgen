# Data Contract Feature Reference

The Data Contract feature surfaces TestGen test suites as a formal, exportable data contract mapped to ODCS v3.1.0 YAML. It provides a health dashboard with top-level coverage, diff, and compliance cards; a coverage matrix across all schema columns organized by enforcement tier; inline term editing via modals; YAML export and import; bulk multi-select term deletion; and contract term difference tracking comparing the saved YAML snapshot against the current live TestGen state. Page entry point: `?table_group_id=<uuid>` on page key `data-contract`.

---

## Requirements

### Health Dashboard

- Must display three top cards on every page load: Coverage, Test Health (being replaced by Contract Term Differences), and Hygiene (being replaced by Contract Term Compliance).
- Must fetch test statuses fresh from the database via `_fetch_test_statuses()` on each render.
- Must not rely on `lastResult` in the cached YAML — it may be stale.

### Coverage Matrix

- Must display a term grid across all schema columns, organized by enforcement tier: `db` (DDL-type), `unf` (observed/undeclared), and `tg` (TestGen-enforced).
- Tier classification must use `_classify_enforcement_tier` in `data_contract_props.py`.

### YAML Export

- Must export a full ODCS v3.1.0 YAML document covering `fundamentals`, `schema`, `quality`, `servers`, `references`, and `compliance` sections.
- Must trigger a browser download directly from the YAML string in props — no `emitEvent` round-trip required.
- Must treat the `schema` section as read-only on import (TestGen is source of truth for column types and classification).
- Must treat `servers` and `references` as read-only on import.

### YAML Import

- Must accept an ODCS v3.1.0 YAML file and apply supported changes back to TestGen.
- Must support creating new tests from rules without an `id` field and write the new UUID back into the uploaded YAML.
- Must support updating existing tests (rules with `id`) for: threshold, tolerance, severity, description, and custom_query.
- Must support updating contract fundamentals: version, status, description.purpose, domain, dataProduct, and slaProperties.latency.
- Must abort the entire import (ERROR) on document-level failures: wrong `apiVersion`, wrong `kind`, missing `id`, invalid `status`, YAML parse error, or table group not found.
- Must skip individual rules with a warning (WARN) on rule-level problems: unsupported metrics (`missingValues`), unsupported operators (`mustNotBe`, `mustNotBeBetween`), `invalidValues` without `arguments.validValues` or `arguments.pattern`, non-TestGen engines (`soda`, `greatExpectations`, `montecarlo`, `dbt`), missing `type`/`metric`/`element`/threshold, stale `id` not in DB, `id` belonging to different table group, or attempt to change immutable `metric` or `element` on an existing test.
- Must silently skip `type: text` rules with no warning.
- Must not delete a test from the database when its rule is omitted from the YAML — must produce an orphan warning instead.
- Must not allow changing `metric` or `element` on an existing test; these fields are immutable.
- Must write new test UUIDs back into the uploaded YAML at the correct positions.
- Must return a `ContractDiff` result object containing: `.test_inserts`, `.test_updates`, `.contract_updates`, `.table_group_updates`, `.warnings`, `.errors`, `.has_errors`, `.total_changes`.
- Must bust YAML, anomaly, and version caches on successful import.

### Bulk Multi-Select Delete

- Must allow entering a selection mode that shows checkboxes on all term chips.
- Must display a running selection count in the toolbar.
- Must require a "Are you sure?" confirmation before executing deletion.
- Must remove test/monitor terms by deleting the rule from the `quality` array in YAML by `rule_id`.
- Must remove DDL terms by removing the relevant field (`physicalType`, `required`, `_logicalTypeOptions.primaryKey`) from the schema properties in YAML.
- Must remove profiling terms by removing the relevant `logicalTypeOptions` subfield from schema properties in YAML.
- Must remove governance terms by resetting the relevant column in `data_column_chars` in the database AND removing the field from YAML.
- Must perform governance DB writes before committing YAML to session state — if any DB write fails, YAML must not be updated.
- Must not allow deleting table-level governance terms (not column-scoped); `_persist_governance_deletion` requires a non-empty `col_name`.
- Must enforce an allowlist in `_GOVERNANCE_LABEL_TO_FIELD` to prevent arbitrary column resets.

### Contract Term Differences

- Must compare the saved contract YAML snapshot against the current live TestGen state and classify every quality term as `same`, `changed`, `new`, or `deleted`.
- Must replace the Test Health and Hygiene top cards with a Contract Diff Summary card and a Compliance Breakdown card.
- Must add a Contract Term Differences tab with four accordions: Changed, New, Deleted, Same.
- Must add a Contract Term Compliance tab with drill-down by Monitors, Tests, and Hygiene.
- Must limit compliance counts to contract-scoped terms only — TestGen tests outside the saved YAML are excluded.
- Must show a "No saved version" placeholder on Cards 2 and 3 when no saved version exists.
- Must never surface terms absent from the saved contract YAML (intentionally deleted terms are not shown as "new").

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
| Staleness | `testgen/commands/contract_staleness.py` | `compute_staleness_diff`, `compute_term_diff` |
| Versions | `testgen/commands/contract_versions.py` | Save/load contract version snapshots |

**Modal pattern:** ALL modals use `emitEvent` → Python `event_handlers` → `@st.dialog`. No VanJS overlays inside the component iframe (iframes clip `position: fixed/absolute`).

**`event_handlers` vs `on_change_handlers`:** Use `event_handlers` when the handler needs to call `st.rerun()` (required for dialogs). `on_change_handlers` does not support `st.rerun()`.

**YAML caching:** Contract YAML is cached in `st.session_state[yaml_key]`. Test run results are not cached — fetched fresh from DB on each render.

---

## DB Schema

| Column | Table | Type | Purpose |
|---|---|---|---|
| `include_in_contract` | `test_suites` | `BOOLEAN NOT NULL DEFAULT TRUE` | Controls which suites are in scope for the contract |
| `is_monitor` | `test_suites` | `BOOLEAN` | Monitor suites — excluded from contract test counts and suite picker |

Migration: `testgen/template/dbupgrade/0183_incremental_upgrade.sql`

---

## Feature Implementation Notes

### Health Dashboard

Three top cards rendered on every page load:

- **Coverage** — percent of schema columns with at least one non-schema quality term; includes a filter link to uncovered columns.
- **Contract Term Differences** — counts of same/changed/new/deleted terms vs. the saved YAML snapshot; clicking a status row navigates to the Contract Term Differences tab.
- **Contract Term Compliance** — enforcement tier breakdown (DB enforced / unenforced / TestGen enforced) with per-monitor, per-test, and hygiene status counts.

Test statuses are fetched fresh from the DB via `_fetch_test_statuses()`. The cached YAML `lastResult` field is not used.

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
- `schema` — columns with physicalType, logicalType, constraints, logicalTypeOptions (min/max/format/etc.), governance fields (CDE, PII, description)
- `quality` — one rule per test definition with operator, threshold, tolerance, severity, suiteId
- `servers`, `references`, `compliance` sections

Entry point: `testgen/commands/export_data_contract.py`

The frontend triggers a browser download (`a.download`) directly from the YAML string in props — no `emitEvent` round-trip needed.

Known limitations:
- `schema`, `servers`, and `references` sections are read-only on import.

---

### YAML Import

Accepts an ODCS v3.1.0 YAML file and applies changes back to TestGen.

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

**Known gaps:**
- Deleting a test via YAML (omitting a rule that exists in DB) is intentionally not supported — produces an orphan warning, not a delete.
- Metric-type changes on existing tests require delete + re-create.

#### YAML Import — Positive Cases

Exhaustive list of YAML quality rules that should import correctly into TestGen, covering creates, updates, and round-trips.

The current export format uses a flat rule structure: `id` (test UUID), `suiteId`, `type`, `metric`, `element` (table.column), and the operator as a key (`mustBe`, `mustBeLessOrEqualTo`, etc.). Creates omit `id`; after import the file is mutated in place with the new UUID.

##### Section 1 — CREATE: New Tests from YAML (no `id` field)

###### 1.1 `nullValues` → `Missing_Pct` (percent, upper tolerance only)

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

###### 1.2 `nullValues` → `Missing_Pct` (exact zero)

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

###### 1.3 `nullValues` → `Missing_Pct` (range band)

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

###### 1.4 `nullValues` → `Missing_Pct` (greater-than threshold)

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

###### 1.5 `rowCount` → `Row_Ct` (minimum)

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

###### 1.6 `rowCount` → `Row_Ct` (range band)

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

###### 1.7 `rowCount` → `Row_Ct` (exact count)

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

###### 1.8 `rowCount` → `Row_Ct` (less-than)

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

###### 1.9 `duplicateValues` → `Dupe_Rows` (exact zero, rows)

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

###### 1.10 `duplicateValues` → `Dupe_Rows` (tolerance, rows)

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

###### 1.11 `duplicateValues` → `Unique_Pct` (percent)

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

###### 1.12 `invalidValues` + `arguments.pattern` → `Pattern_Match`

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

###### 1.13 `invalidValues` + `arguments.pattern` + tolerance → `Pattern_Match`

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

###### 1.14 `invalidValues` + `arguments.validValues` → `LOV_Match`

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

###### 1.15 `invalidValues` + `arguments.validValues` + tolerance

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

###### 1.16 `sql` type → `CUSTOM`

```yaml
- name: recent_orders_exist
  type: sql
  query: "SELECT COUNT(*) FROM orders WHERE created_at > CURRENT_DATE - INTERVAL '7 days'"
  mustBeGreaterThan: 0
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `CUSTOM`, query stored in `custom_query`, `skip_errors = 0` derived from threshold.

---

###### 1.17 `sql` type with `mustBeLessOrEqualTo` (skip_errors semantics)

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

###### 1.18 `custom/vendor:testgen` + `testType` → any TestGen type (round-trip restore)

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

###### 1.19 `custom/vendor:testgen` + `testType: Schema_Drift`

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

###### 1.20 `custom/vendor:testgen` + `testType: Distribution_Shift`

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

###### 1.21 Create with description and dimension fields

```yaml
- name: customer_id_completeness
  description: "All customer records must have a valid ID — no null or missing values permitted."
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

###### 1.22 Create with no `suiteId` — defaults to first included suite

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

##### Section 2 — UPDATE: Modify Existing Tests (rule has `id`)

###### 2.1 Update threshold value only

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

###### 2.2 Update severity only

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111112"
  name: order_id_no_dups
  type: library
  metric: duplicateValues
  mustBe: 0
  unit: rows
  element: orders.order_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Warning   # was Fail
```

Expected: only `severity` updated.

---

###### 2.3 Update test description (name field)

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111113"
  name: "Order IDs must be globally unique — no duplicate order numbers"   # changed
  type: library
  metric: duplicateValues
  mustBe: 0
  unit: rows
  element: orders.order_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Fail
```

Expected: `test_description` updated.

---

###### 2.4 Update tolerance band (mustBeBetween)

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111114"
  name: orders_row_range
  type: library
  metric: rowCount
  mustBeBetween: [2000, 200000]   # was [1000, 100000]
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `lower_tolerance = "2000"`, `upper_tolerance = "200000"`.

---

###### 2.5 Update custom_query on CUSTOM test

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111115"
  name: recent_orders_exist
  type: sql
  query: "SELECT COUNT(*) FROM orders WHERE created_at > CURRENT_DATE - INTERVAL '30 days'"   # was 7 days
  mustBeGreaterThan: 0
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `custom_query` updated.

---

###### 2.6 Update skip_errors on CUSTOM test

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111116"
  name: orphan_check
  type: sql
  query: "SELECT COUNT(*) FROM order_lines ol LEFT JOIN orders o ON o.id = ol.order_id WHERE o.id IS NULL"
  mustBeLessOrEqualTo: 5   # was 0 — allow up to 5 errors
  unit: rows
  element: order_lines
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `skip_errors = 5`.

---

###### 2.7 Multiple fields updated at once

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111117"
  name: "Email null rate — tightened threshold"   # changed
  type: library
  metric: nullValues
  mustBeLessOrEqualTo: 1.0   # was 5.0
  unit: percent
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Fail              # was Warning — changed
```

Expected: both `threshold_value` and `severity` updated in one DB write.

---

###### 2.8 No-op update — nothing changed

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111118"
  name: email_null_pct
  type: library
  metric: nullValues
  mustBeLessOrEqualTo: 5.0   # same as DB
  unit: percent
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: Fail              # same as DB
```

Expected: no DB write, test appears in "no change" count in import report.

---

###### 2.9 Update CUSTOM test threshold (Avg_Shift)

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111119"
  name: amount_avg_shift
  type: custom
  vendor: testgen
  testType: Avg_Shift
  mustBeLessOrEqualTo: 5.0   # was 10.0
  unit: rows
  element: orders.amount
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `threshold_value = "5.0"`, `lock_refresh = "Y"`.

---

###### 2.10 Update — clear lower/upper tolerance by switching to single threshold

Behavior: if `mustBeBetween` is gone and a scalar operator is present, clear `lower_tolerance`/`upper_tolerance` and set `threshold_value`.

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111120"
  name: orders_row_min
  type: library
  metric: rowCount
  mustBeGreaterOrEqualTo: 500   # was mustBeBetween [1000, 100000]
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

Expected: `lower_tolerance = NULL`, `upper_tolerance = NULL`, `threshold_value = "500"`.

---

##### Section 3 — ROUND-TRIP Tests

###### 3.1 Export → import unchanged → no diff

Export a contract YAML from TestGen. Import it back without modification.

Expected: `ContractDiff.total_changes == 0`, all tests in "no change" bucket.

---

###### 3.2 Export → change one threshold → import → single test updated

Export. Change `mustBeLessOrEqualTo: 5.0` → `mustBeLessOrEqualTo: 2.0` on one rule. Import.

Expected: exactly one `test_updates` entry with `threshold_value = "2.0"`.

---

###### 3.3 Export → add new rule (no id) → import → test created + id written back

Export. Append a new rule with no `id`. Import.

Expected:
- New test created in DB
- YAML file on disk now contains `id: "<new-uuid>"` on that rule
- Import report shows 1 created

---

###### 3.4 Export → change contract version → import → fundamentals updated

```yaml
version: "2.0.0"   # was "1.0.0"
```

Expected: `ContractDiff.contract_updates["contract_version"] == "2.0.0"`.

---

###### 3.5 Export → remove a rule → import → orphan warning, no delete

Export. Delete one `quality` entry from the YAML. Import.

Expected:
- No test deleted from DB
- Warning in import report: "Test `<id>` present in DB but not in YAML — not deleted"
- `ContractDiff.warnings` contains one entry

---

###### 3.6 Full round-trip: create → export → import back → no diff

1. Import a new rule (no id) → test created, id written back.
2. Export the contract.
3. Import the exported contract unchanged.

Expected: step 3 produces zero changes.

---

###### 3.7 Round-trip with severity change

1. Export — rule has `severity: Fail`
2. Change to `severity: Warning` in YAML
3. Import
4. Export again

Expected: step 3 shows 1 update; step 4 YAML shows `severity: Warning`.

---

###### 3.8 Round-trip preserves `suiteId`

Export includes `suiteId`. Import back with same `suiteId`. Test stays in the same suite.

---

##### Section 4 — WRITE-BACK Behavior

###### 4.1 New test id written at correct YAML location

Given a multi-rule quality list where the new rule is the 3rd entry, the write-back must add `id:` to the 3rd entry only, not disturb others.

---

###### 4.2 Multiple new tests — all ids written back

Import YAML with 3 new rules (no id). All 3 tests created. All 3 rules in YAML file get their new ids.

---

###### 4.3 Mixed create + update — file written correctly

YAML has: 2 existing rules (with id) + 1 new rule (no id). After import:
- Existing rules: ids unchanged
- New rule: id written back
- File is valid YAML after write-back

---

###### 4.4 Write-back preserves YAML comments and formatting as much as possible

YAML file has comments. After write-back, comments on other rules are preserved. (Note: ruamel.yaml preferred over pyyaml for this.)

---

###### 4.5 Write-back is idempotent — importing twice does not duplicate ids

Import → id written. Import again (now has id) → update path taken, no second id written.

---

##### Section 5 — FUNDAMENTALS Updates (non-quality fields)

###### 5.1 Version update

```yaml
version: "2.1.0"
```

Expected: `contract_version = "2.1.0"`.

---

###### 5.2 Status update

```yaml
status: active
```

Expected: `contract_status = "active"`.

---

###### 5.3 Description purpose update

```yaml
description:
  purpose: "Daily order processing pipeline — SLA 99.9% within 4 hours."
```

Expected: table group `description` updated.

---

###### 5.4 Domain update

```yaml
domain: "commerce"
```

Expected: `business_domain = "commerce"`.

---

###### 5.5 Data product update

```yaml
dataProduct: "order-management"
```

Expected: `data_product = "order-management"`.

---

###### 5.6 SLA latency update

```yaml
slaProperties:
  - property: latency
    value: 4
    unit: day
```

Expected: `profiling_delay_days = 4`.

---

###### 5.7 All fundamentals updated at once

All of the above in a single import. Expected: single UPDATE on `table_groups` with all changed columns.

---

#### YAML Import — Failure Cases

ODCS quality rules that are spec-valid but cannot be imported into TestGen, or that result in partial failures, warnings, or skips.

**Conventions:**
- `ERROR` — import aborts for this rule; logged to import report errors list
- `WARN` — rule skipped; logged to import report warnings list
- `SKIP` — rule silently ignored (e.g., `text` type)

##### Section 1 — Unsupported Metric Types

###### 1.1 `missingValues` metric — no TestGen equivalent

```yaml
- name: empty_string_check
  type: library
  metric: missingValues
  mustBe: 0
  unit: rows
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  arguments:
    missingValues: ["", "N/A", "NULL", "UNKNOWN"]
```

**WARN**: `metric: missingValues` has no TestGen test type equivalent. TestGen checks SQL NULL only. Rule skipped.

---

###### 1.2 `missingValues` with no arguments

```yaml
- name: undefined_missing
  type: library
  metric: missingValues
  mustBe: 0
  unit: rows
  element: orders.status
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `metric: missingValues` not supported. Rule skipped.

---

##### Section 2 — Unsupported Operators

###### 2.1 `mustNotBe` operator

```yaml
- name: id_must_not_be_zero
  type: library
  metric: nullValues
  mustNotBe: 0
  unit: rows
  element: orders.order_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `mustNotBe` operator has no direct TestGen test_operator mapping. Rule skipped.

---

###### 2.2 `mustNotBeBetween` operator on rowCount

```yaml
- name: row_count_not_in_danger_zone
  type: library
  metric: rowCount
  mustNotBeBetween: [0, 100]
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `mustNotBeBetween` has no TestGen test_operator mapping. Rule skipped.

---

###### 2.3 `mustNotBeBetween` operator on nullValues

```yaml
- name: null_pct_not_in_range
  type: library
  metric: nullValues
  mustNotBeBetween: [10, 90]
  unit: percent
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `mustNotBeBetween` not supported. Rule skipped.

---

###### 2.4 `mustNotBe` operator on duplicateValues

```yaml
- name: require_some_duplicates
  type: library
  metric: duplicateValues
  mustNotBe: 0
  unit: rows
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `mustNotBe` not supported. Rule skipped.

---

##### Section 3 — `invalidValues` Without Actionable Arguments

###### 3.1 `invalidValues` with no `arguments` block

```yaml
- name: status_no_invalids
  type: library
  metric: invalidValues
  mustBe: 0
  unit: rows
  element: orders.status
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `metric: invalidValues` requires either `arguments.validValues` or `arguments.pattern` to create a TestGen test. Neither provided. Rule skipped.

---

###### 3.2 `invalidValues` with empty `arguments` block

```yaml
- name: status_no_invalids
  type: library
  metric: invalidValues
  mustBe: 0
  unit: rows
  element: orders.status
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  arguments: {}
```

**WARN**: `arguments` present but contains no `validValues` or `pattern`. Rule skipped.

---

###### 3.3 `invalidValues` with only `missingValues` argument (sentinel list)

```yaml
- name: treat_blanks_as_invalid
  type: library
  metric: invalidValues
  mustBe: 0
  unit: rows
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  arguments:
    missingValues: ["", " "]
```

**WARN**: `arguments.missingValues` (sentinel value exclusion) is not supported by TestGen. `arguments.validValues` or `arguments.pattern` required. Rule skipped.

---

###### 3.4 `invalidValues` with `validValues` as empty list

```yaml
- name: status_empty_lov
  type: library
  metric: invalidValues
  mustBe: 0
  unit: rows
  element: orders.status
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  arguments:
    validValues: []
```

**WARN**: `arguments.validValues` is empty — cannot create a valid-values test with no allowed values. Rule skipped.

---

##### Section 4 — Non-TestGen Custom Engines

###### 4.1 `custom` type with `engine: soda`

```yaml
- name: soda_nullcheck
  type: custom
  engine: soda
  mustBe: 0
  unit: rows
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `engine: soda` rules can only be executed by Soda Core — not importable into TestGen. Rule skipped.

---

###### 4.2 `custom` type with `engine: greatExpectations`

```yaml
- name: ge_expect_column_values_to_not_be_null
  type: custom
  engine: greatExpectations
  expectation: expect_column_values_to_not_be_null
  mustBe: 0
  unit: rows
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `engine: greatExpectations` not supported by TestGen import. Rule skipped.

---

###### 4.3 `custom` type with `engine: montecarlo`

```yaml
- name: mc_field_health
  type: custom
  engine: montecarlo
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `engine: montecarlo` not supported. Rule skipped.

---

###### 4.4 `custom` type with `engine: dbt`

```yaml
- name: dbt_not_null
  type: custom
  engine: dbt
  test: not_null
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `engine: dbt` not supported. Rule skipped.

---

###### 4.5 `custom/vendor:testgen` but missing `testType` field

```yaml
- name: some_testgen_test
  type: custom
  vendor: testgen
  mustBeLessOrEqualTo: 5.0
  unit: rows
  element: orders.amount
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `type: custom, vendor: testgen` requires `testType` field. Rule skipped.

---

###### 4.6 `custom/vendor:testgen` with unknown `testType`

```yaml
- name: unknown_test
  type: custom
  vendor: testgen
  testType: Fake_Test_That_Does_Not_Exist
  mustBeLessOrEqualTo: 0
  unit: rows
  element: orders.amount
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `testType: Fake_Test_That_Does_Not_Exist` is not a valid TestGen test type. Rule skipped.

---

##### Section 5 — `type: text` (No Operational Value)

###### 5.1 Text rule silently skipped

```yaml
- name: orders_data_quality_policy
  type: text
  description: "All orders must conform to the data quality standards defined in DQP-2024-001."
  element: orders
```

**SKIP**: `type: text` is documentation only. No test created. Not logged as warning.

---

###### 5.2 Text rule with dimension

```yaml
- name: completeness_policy
  type: text
  description: "All required fields must be populated per the data contract."
  dimension: completeness
```

**SKIP**: same as above.

---

##### Section 6 — `sql` Type Problems

###### 6.1 `sql` type with no `query` field

```yaml
- name: missing_query
  type: sql
  mustBeGreaterThan: 0
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `type: sql` requires a `query` field. Rule skipped.

---

###### 6.2 `sql` type with empty `query`

```yaml
- name: empty_query
  type: sql
  query: ""
  mustBeGreaterThan: 0
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `query` is empty. Rule skipped.

---

###### 6.3 `sql` type with no threshold operator

```yaml
- name: no_threshold
  type: sql
  query: "SELECT COUNT(*) FROM orders WHERE status = 'error'"
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: No threshold operator found (`mustBe`, `mustBeLessOrEqualTo`, etc.). Rule skipped.

---

##### Section 7 — Missing Required Fields

###### 7.1 No `type` field on rule

```yaml
- name: mystery_rule
  metric: nullValues
  mustBe: 0
  unit: rows
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `type` field is required on all quality rules. Rule skipped.

---

###### 7.2 `library` type with no `metric`

```yaml
- name: no_metric
  type: library
  mustBe: 0
  unit: rows
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `metric` is required for `type: library`. Rule skipped.

---

###### 7.3 `library` type with unrecognized `metric`

```yaml
- name: unknown_metric
  type: library
  metric: dataFreshness
  mustBeLessOrEqualTo: 5
  unit: hours
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `metric: dataFreshness` is not a recognized ODCS library metric. Rule skipped.

---

###### 7.4 No `element` field (column/table unknown for creates)

```yaml
- name: needs_element
  type: library
  metric: nullValues
  mustBe: 0
  unit: percent
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: CREATE requires `element` field to determine table/column. Rule skipped.

---

###### 7.5 No threshold operator at all

```yaml
- name: no_operator
  type: library
  metric: nullValues
  unit: percent
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: No threshold operator found. Cannot determine test threshold. Rule skipped.

---

##### Section 8 — Update Path Failures (rule has `id`)

###### 8.1 `id` not found in DB — stale reference

```yaml
- id: "ffffffff-dead-beef-0000-000000000000"
  name: stale_test
  type: library
  metric: nullValues
  mustBe: 0
  unit: percent
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: Test `ffffffff-dead-beef-0000-000000000000` not found in table group — may have been deleted. Rule skipped.

---

###### 8.2 `id` found but belongs to a different table group

```yaml
- id: "bbbbbbbb-2222-2222-2222-222222222222"   # valid UUID but in a different table group
  name: foreign_test
  type: library
  metric: nullValues
  mustBe: 0
  unit: percent
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: Test UUID exists but does not belong to this table group. Rule skipped.

---

###### 8.3 Attempt to change `metric` (immutable — test type change)

This is detected by comparing the existing test_type against what the YAML `metric` implies.

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111111"   # existing Missing_Pct test
  name: email_null_pct
  type: library
  metric: duplicateValues   # was nullValues — changing metric means new test type
  mustBe: 0
  unit: rows
  element: customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: Changing `metric` would change the test type, which is immutable on an existing test. Rule skipped. If a new test is intended, remove the `id` field.

---

###### 8.4 Attempt to change `element` (immutable — column/table change)

```yaml
- id: "aaaaaaaa-1111-1111-1111-111111111111"   # existing test on customers.email
  name: email_null_pct
  type: library
  metric: nullValues
  mustBeLessOrEqualTo: 5.0
  unit: percent
  element: customers.phone   # was customers.email
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: Changing `element` would change the column/table the test runs on, which is immutable on an existing test. Remove `id` to create a new test. Rule skipped.

---

##### Section 9 — Malformed Values

###### 9.1 Threshold value is non-numeric string

```yaml
- name: bad_threshold
  type: library
  metric: nullValues
  mustBeLessOrEqualTo: "high"
  unit: percent
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: Threshold value `"high"` is not numeric. Rule skipped.

---

###### 9.2 `mustBeBetween` is not an array

```yaml
- name: bad_between
  type: library
  metric: rowCount
  mustBeBetween: 1000
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `mustBeBetween` must be a two-element array `[low, high]`. Got scalar. Rule skipped.

---

###### 9.3 `mustBeBetween` array has wrong length

```yaml
- name: bad_between_length
  type: library
  metric: rowCount
  mustBeBetween: [1000]
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `mustBeBetween` must be `[low, high]` — got 1 element. Rule skipped.

---

###### 9.4 `mustBeBetween` with non-numeric bounds

```yaml
- name: bad_between_types
  type: library
  metric: rowCount
  mustBeBetween: ["low", "high"]
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `mustBeBetween` bounds must be numeric. Rule skipped.

---

###### 9.5 `mustBeBetween` lower > upper (inverted range)

```yaml
- name: inverted_range
  type: library
  metric: rowCount
  mustBeBetween: [100000, 1000]
  unit: rows
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `mustBeBetween` lower bound (100000) is greater than upper bound (1000). Rule skipped.

---

###### 9.6 Invalid `severity` value

```yaml
- name: bad_severity
  type: library
  metric: nullValues
  mustBe: 0
  unit: percent
  element: orders.customer_id
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
  severity: critical   # not a valid TestGen severity
```

**WARN**: `severity: critical` is not a valid TestGen severity (`Log`, `Warning`, `Fail`, `Error`). Severity ignored; test created with default severity `Fail`.

Note: this is a WARN + partial success — rule still imports, just severity falls back to default.

---

##### Section 10 — Document-Level Failures

###### 10.1 YAML parse error

```
quality:
  - name: broken
    type: library
  metric: nullValues   # bad indentation
```

**ERROR**: YAML parse failed. Entire import aborted.

---

###### 10.2 Wrong `apiVersion`

```yaml
apiVersion: v2.0.0
kind: DataContract
id: "contract-001"
```

**ERROR**: Expected `apiVersion: v3.1.0`. Import aborted.

---

###### 10.3 Wrong `kind`

```yaml
apiVersion: v3.1.0
kind: Schema
id: "contract-001"
```

**ERROR**: Expected `kind: DataContract`. Import aborted.

---

###### 10.4 Missing `id` field on document

```yaml
apiVersion: v3.1.0
kind: DataContract
version: "1.0.0"
```

**ERROR**: Missing required field `id`. Import aborted.

---

###### 10.5 Invalid document `status` value

```yaml
apiVersion: v3.1.0
kind: DataContract
id: "contract-001"
status: published   # not in ODCS valid statuses
```

**ERROR**: Invalid `status: published`. Must be one of: `active`, `deprecated`, `draft`, `proposed`, `retired`. Import aborted.

---

###### 10.6 Table group not found

Correct YAML structure, but `table_group_id` passed to `run_import_data_contract` does not exist in DB.

**ERROR**: `Table group '<uuid>' not found.` Import aborted.

---

##### Section 11 — Suite Resolution Failures (CREATE path)

###### 11.1 `suiteId` not found in table group

```yaml
- name: orphan_suite_test
  type: library
  metric: nullValues
  mustBe: 0
  unit: percent
  element: orders.customer_id
  suiteId: "ffffffff-dead-beef-0000-bad000000000"   # not a real suite
```

**WARN**: `suiteId: ffffffff-dead-beef-0000-bad000000000` not found in table group. Rule skipped.

---

###### 11.2 No `suiteId` and table group has no included suites

Rule has no `suiteId`, table group has zero included (non-monitor) test suites.

**WARN**: No `suiteId` provided and no default suite available for table group. Rule skipped.

---

##### Section 12 — `rowCount` Unit Ambiguity

###### 12.1 `rowCount` with `unit: percent` — undefined semantics

```yaml
- name: row_count_percent
  type: library
  metric: rowCount
  mustBeGreaterThan: 80
  unit: percent   # percent of what?
  element: orders
  suiteId: "aaaaaaaa-0000-0000-0000-000000000001"
```

**WARN**: `metric: rowCount` with `unit: percent` has no defined semantics in TestGen. Use `unit: rows` for row count tests. Rule skipped.

---

### Bulk Multi-Select Delete

User flow:
1. Click **Select** button in the terms toolbar → enters selection mode (`_selectionMode.val = true`)
2. Checkboxes appear on all term chips
3. Click individual chips to toggle selection; a running count appears in the toolbar
4. Click **Delete contract terms** → shows "Are you sure?" confirmation prompt
5. Click **Yes, delete** → `confirmDelete()` → `emitEvent('BulkDeleteTermsClicked', { terms: [...] })` → Python `on_bulk_delete_terms`

What gets deleted by term source:

| Source | Action |
|---|---|
| `test` / `monitor` | Rule removed from `quality` array in YAML by `rule_id` |
| `ddl` | Field (`physicalType`, `required`, `_logicalTypeOptions.primaryKey`) removed from `schema[].properties[]` |
| `profiling` | `logicalTypeOptions` subfield (`minimum`, `maximum`, `minLength`, `maxLength`, `format`, `logicalType`) removed from `schema[].properties[]` |
| `governance` | `criticalDataElement` or `description` removed from YAML **and** DB column in `data_column_chars` reset via `_persist_governance_deletion` |

Atomicity: governance DB writes happen before YAML is committed to `st.session_state`. If any DB write fails, YAML is not updated and an error banner is shown.

Key files:
- `testgen/ui/components/frontend/js/pages/data_contract.js` — `enterSelectionMode`, `exitSelectionMode`, `confirmDelete`, `BulkDeleteTermsClicked`
- `testgen/ui/views/data_contract.py:on_bulk_delete_terms` — handler
- `testgen/ui/views/data_contract_yaml.py:_delete_term_yaml_patch` — YAML field removal for DDL/profiling/governance terms
- `testgen/ui/queries/data_contract_queries.py:_persist_governance_deletion` — DB write for governance deletions
- `testgen/ui/queries/data_contract_queries.py:_GOVERNANCE_LABEL_TO_FIELD` — label → (db_column, reset_value) map with allowlist enforcement

Tests: `tests/unit/ui/test_bulk_delete_terms.py` — 20 unit tests covering `_GOVERNANCE_LABEL_TO_FIELD` completeness and allowlist safety, `_persist_governance_deletion` guard conditions, YAML mutation for all term sources, and partial-failure safety.

Known limitations:
- Table-level governance terms (not column-scoped) are not deletable — `_persist_governance_deletion` requires a non-empty `col_name`.
- PII term editing/deletion requires `view_pii` permission to render the chip in the first place.
- Governance terms are sourced from `data_column_chars` DB, not YAML — deletions must always write to DB, not just YAML.

---

## Contract Term Differences

Design spec: `docs/superpowers/specs/2026-04-08-data-contract-differences-design.md`
Implementation plan: `docs/superpowers/plans/2026-04-08-contract-term-differences.md`

### Overview

Add a Contract Term Differences tab to the Data Contract page and replace the existing Test Health and Hygiene top cards with two new cards that surface contract drift and compliance at a glance.

The core idea: compare the saved contract version (YAML snapshot) against the current live TestGen state, classify every quality term by its drift status (same / changed / new / deleted), and show enforcement-tier compliance for the terms TestGen actively runs.

### Scope

**What changes:**
1. `testgen/commands/contract_staleness.py` — new `TermStatus`, `TermDiffEntry`, `TermDiffResult` data structures and `compute_term_diff()` function
2. `testgen/ui/views/data_contract.py` — replace `_render_health_dashboard()` cards 2 & 3; add Contract Term Differences tab to page render
3. `testgen/ui/views/data_contract_props.py` — no change (existing `_classify_enforcement_tier` tiers reused)

**What does not change:**
- Coverage card content — unchanged; label is renamed (see Card 1 below)
- Existing `StaleDiff` / `compute_staleness_diff` — kept for the staleness banner
- Version picker, save/regenerate toolbar, unsaved changes banner

### Data Model

Term statuses:
```python
TermStatus = Literal["same", "changed", "new", "deleted"]
```

| Status | Meaning |
|---|---|
| `same` | Exists in saved contract and current TestGen; no meaningful change |
| `changed` | Exists in both; threshold or config differs |
| `new` | In current TestGen but absent from the saved contract |
| `deleted` | In saved contract but no longer in current TestGen |

**Key rule:** Terms absent from the saved contract YAML (i.e. previously intentionally deleted) are never surfaced. The diff is purely from the saved contract's perspective.

Data structures:
```python
@dataclass
class TermDiffEntry:
    element: str          # "table.column" or "table" for table-level
    test_type: str
    status: TermStatus
    detail: str | None    # inline detail for "changed" rows; None for others
    last_result: str | None  # pass/fail/not run from latest test run

@dataclass
class TermDiffResult:
    entries: list[TermDiffEntry]

    # Top-card counts
    saved_count: int
    current_count: int

    # Enforcement-tier compliance (for Card 3) — contract-scoped terms only
    db_count: int
    unenforced_count: int
    tg_count: int
    # Tests & monitors: Passed / Failed / Warning / Error / Not Run
    tg_monitor_passed: int
    tg_monitor_failed: int
    tg_monitor_warning: int
    tg_monitor_error: int
    tg_monitor_not_run: int
    tg_test_passed: int
    tg_test_failed: int
    tg_test_warning: int
    tg_test_error: int
    tg_test_not_run: int
    # Hygiene: Definite / Likely / Possible
    tg_hygiene_definite: int
    tg_hygiene_likely: int
    tg_hygiene_possible: int
```

### `compute_term_diff(table_group_id, saved_yaml) -> TermDiffResult`

Located in `contract_staleness.py`.

**Algorithm:**
1. Parse saved YAML `quality` array → build index `{rule_id: rule}`
2. Query current TestGen test definitions (same query as `compute_staleness_diff`)
3. For each rule in saved YAML:
   - Found in TestGen + same threshold → `same`
   - Found in TestGen + different threshold → `changed`, set `detail = "threshold: X → Y"`
   - Not found in TestGen → `deleted`
4. For each TestGen definition not in saved YAML → `new`
5. Classify each TestGen-enforced entry by monitor / test / hygiene subtype using existing suite `is_monitor` flag and test type
6. Count enforcement tiers using `_classify_enforcement_tier` logic applied to the saved YAML terms

### Card 1 — Contract Term Coverage (replaces Coverage)

Card label is dynamic: **"Version {N} Contract Term Coverage"** (e.g. "Version 12 Contract Term Coverage").
Content is unchanged from the current Coverage card.
The existing "Contract Claim Completeness" tab is renamed to **"Contract Term Coverage"**.

### Card 2 — Contract Diff Summary (replaces Test Health)

Card label is dynamic: **"Version {N} Contract Term Differences"** (e.g. "Version 12 Contract Term Differences").

Vertical layout:
```
Version 12 Contract Term Differences
Saved: 100  ·  Current: 101
─────────────────────────────
 90  same
  8  changed
  1  deleted
  1  new
```

- Each status line is clickable and filters the Contract Term Differences tab to that status
- Shows "No saved version" state gracefully if no version exists

### Card 3 — Compliance Breakdown (replaces Hygiene)

Card label is dynamic: **"Version {N} Contract Term Compliance"** (e.g. "Version 12 Contract Term Compliance").

Vertical layout:
```
Version 12 Contract Term Compliance
──────────────────────────────────────
30  database enforced
20  unenforced
40  TestGen enforced
      Monitors  3 passed
      Tests     24 passed  1 warning  1 failed
      Hygiene   2 definite  3 likely  4 possible
```

- `database enforced` = `"db"` tier from `_classify_enforcement_tier` (DDL-type terms)
- `unenforced` = `"unf"` tier (observed or undeclared terms)
- `TestGen enforced` = `"tg"` tier, broken out by:
  - **Monitors** — suites where `is_monitor = TRUE`; statuses: Passed / Failed / Warning / Error / Not Run
  - **Tests** — standard test suite definitions; statuses: Passed / Failed / Warning / Error / Not Run
  - **Hygiene** — profiling anomaly findings; statuses: Definite / Likely / Possible
- Scope: only contract terms (rule IDs in the saved YAML) are counted — TestGen tests outside the contract are excluded
- Counts pulled from `_fetch_test_statuses()` and `_fetch_anomalies()` (already fetched on page load)

### Differences Tab

A new tab added to the contract page tab bar, between the existing tabs and the YAML view.

**Layout — four accordions, top to bottom:**

**1. Changed** (expanded by default if non-empty)
```
orders.amount      Numeric_Range    threshold: 5 → 8
users.email        Valid_Email       pattern: .* → ^[^@]+@[^@]+$
```
Each row: `element` · `test_type` · `detail` inline

**2. New** (expanded by default if non-empty)
```
orders.created_at  Not_Null
```
Each row: `element` · `test_type` — no detail (entire term is new)

**3. Deleted** (expanded by default if non-empty)
```
users.phone        Valid_Phone       removed from TestGen
```
Each row: `element` · `test_type` · "removed from TestGen"

**4. Same** (collapsed by default)
```
customers.id       Not_Null
customers.name     Not_Empty
```
Each row: `element` · `test_type` — no detail needed

Accordion behavior:
- Accordion header shows count: e.g. `Changed (8)`
- Same accordion starts collapsed; all others start expanded if they have entries
- If a category has 0 entries, the accordion is hidden entirely

Filtering from top cards: clicking a status chip on Card 2 (same / changed / deleted / new) deep-links to the Contract Term Differences tab with that accordion pre-expanded and others collapsed.

### Empty / Edge States

| Condition | Behavior |
|---|---|
| No saved version | Cards 2 & 3 show "No contract saved yet" placeholder |
| All terms same | Contract Term Differences tab shows only the Same accordion, expanded |
| No TestGen tests | `tg_count = 0`; Card 3 shows database enforced + unenforced only |
| Viewing a historic version | Cards 2 & 3 still compute diff against that version vs. current TestGen; read-only banner remains |

### Contract Term Compliance Tab

A fifth tab — **Contract Term Compliance** — provides term-by-term drill-down of Card 3.

**Scope note:** Only the N contract terms whose IDs appear in the saved YAML are evaluated. TestGen tests outside the contract are excluded entirely.

**Three accordions** (all expanded by default if non-empty):

**Monitors** — each row: `element` · `test_type` · status chip. Statuses: `Passed` · `Failed` · `Warning` · `Error` · `Not Run`

**Tests** — each row: `element` · `test_type` · status chip. Statuses: `Passed` · `Failed` · `Warning` · `Error` · `Not Run`

**Hygiene** — each row: `element` · `anomaly_type` · likelihood chip. Statuses: `Definite` · `Likely` · `Possible`

Accordion headers show aggregate status counts, e.g.:
```
Tests    24 passed  1 warning  1 failed  2 not run
Hygiene  2 definite  3 likely  4 possible
```

### Implementation Status

**Complete.** All tasks implemented and committed on branch `data-contracts-vibe`.

| Task | Status |
|---|---|
| Task 1: `compute_term_diff` data structures in `contract_staleness.py` | Complete |
| Task 2: Wire into `data_contract.py` props | Complete |
| Task 3: Frontend cards (Card 1 rename, Card 2, Card 3) | Complete |
| Task 4: Contract Term Differences tab | Complete |
| Task 5: Contract Term Compliance tab | Complete |

**Post-implementation bug fixes:**
- Float/string threshold mismatch: normalized both sides to float before comparison
- Range thresholds always showing "changed": fixed by fetching `lower_tolerance` + `upper_tolerance` separately from the DB and building a `"lower,upper"` comparison string
- Referential tests (e.g. `Aggregate_Balance`) appearing as "new": filtered out by joining `test_types` and excluding `test_scope = 'referential'`

### Files Changed

| File | Change |
|---|---|
| `testgen/commands/contract_staleness.py` | Add `TermStatus`, `TermDiffEntry`, `TermDiffResult`, `compute_term_diff()` |
| `testgen/ui/views/data_contract.py` | Replace cards 1 label, 2 & 3 in `_render_health_dashboard()`; add Contract Term Differences and Contract Term Compliance tabs |
| `testgen/ui/components/frontend/js/pages/data_contract.js` | Rename "Contract Claim Completeness" tab to "Contract Term Coverage"; add "Contract Term Differences" and "Contract Term Compliance" tabs and their rendered content |

No new files. No DB schema changes.

---

## Planned Work (To-Do)

### 1. Create New Contract Terms Directly from the UI

Users should be able to add governance and schema terms (description, CDE, PII, data type, etc.) to a column directly from the Data Contract page, without leaving the contract view or going through a separate profiling/governance form.

**Open questions:**
- Which term types are in scope for inline creation (governance only, or DDL/profiling too)?
- Should this be an inline edit on the term chip or a modal?

---

### 2. Create New Tests Directly from the Contract UI

Users should be able to author a new quality test (e.g. `Missing_Pct`, `LOV_Match`, `CUSTOM`) for any column directly from the Data Contract page. Today tests can only be created via test generation or the test suites UI.

**Open questions:**
- Which test types should be creatable inline vs. requiring the full test editor?
- How does the new test get assigned to a suite — user picks, or defaults to the first included suite?

---

### 3. Freeze a New Test Suite on Contract Save

When the user saves a contract version snapshot, automatically create a new frozen test suite containing exactly the tests referenced by that contract version. This gives a stable, reproducible test run baseline tied to each contract version.

**Open questions:**
- Is the frozen suite read-only (no add/remove), or just a named snapshot that can be cloned?
- Should `include_in_contract` be set to `FALSE` on frozen suites so they don't pollute the live contract view?
- Naming convention: e.g. `<table_group_name>_contract_v<N>`?

---

### 4. Flag TestGen-Only Tests Not Part of the ODCS Standard

Some TestGen test types (e.g. `Avg_Shift`, `Distribution_Shift`, `Schema_Drift`, `Aggregate_Balance`) have no equivalent in the ODCS v3.1.0 `library` metric vocabulary. When saved to a contract or displayed in the contract view, these tests should be clearly labeled as "TestGen extension" so contract consumers understand they are not portable to other ODCS-compatible tools.

**Open questions:**
- Where should the label appear — chip badge, tooltip, export annotation?
- Should ODCS export use `type: custom, vendor: testgen, testType: <X>` for these (already done for some) — confirm coverage is complete?
- Should the YAML import importer warn when it encounters a `vendor: testgen` test type that is not in the standard library?

---

### 5. ~~Governance Fields Writable on YAML Import~~ ✅ Implemented

The `schema` section now round-trips fully. `compute_import_diff` in `odcs_contract.py` reads governance fields from `schema[].properties[]` — both ODCS standard fields (`description`, `criticalDataElement`, `classification`) and `customProperties[testgen.*]` entries (`pii_flag`, `data_source`, `source_system`, etc.) — and adds them to `ContractDiff.governance_updates`. `apply_import_diff` writes those updates to `data_column_chars` through an allowlist-guarded UPDATE path.

**ODCS compliance migration also shipped simultaneously:**
- Export now writes profiling stats and DDL constraints as `customProperties` with `testgen.*` keys instead of `logicalTypeOptions`
- Column-level tag fields (`data_source`, `source_system`, `source_process`, `business_domain`, `stakeholder_group`, `transform_level`, `aggregation_level`, `data_product`) are exported as `testgen.*` customProperties per column
- `pii_flag` stored as both `classification` (ODCS standard, lossy) and `testgen.pii_flag` (exact value, lossless round-trip)
- Display code (`data_contract_props.py`) reads from either format via `_prop_opts()` bridge helper for backward compatibility with existing contracts

---

### 6. Test Deletion via YAML Import

Currently, omitting a rule from an uploaded YAML that exists in the DB produces an orphan warning and no action. For users treating the YAML as source of truth, there is no supported way to delete a test via the import path. This should be a deliberate opt-in (e.g. a `--allow-deletes` flag or a document-level `allowDeletions: true` field) to avoid accidental data loss.

**Open questions:**
- Should deletion be opt-in at the document level or via an import UI toggle?
- How should the import report surface pending deletions before they are applied?
- Should deleted tests be hard-deleted or soft-deleted (`test_active = 'N'`)?

---

### 7. Version-to-Version Diff

Today the Contract Term Differences tab always compares the selected saved version against the current live TestGen state. There is no way to compare two saved snapshots against each other (e.g. v3 vs. v7) to understand how the contract evolved over time. This would let users audit changes between releases or reviews.

**Open questions:**
- Should this be a separate "Compare versions" view, or an extension of the existing Differences tab with a version picker for both sides?
- Is the comparison purely YAML-based (diff the two quality arrays), or should it also pull live test status for each version?

---

### 8. Bulk Governance Edit

The multi-select delete feature allows bulk removal of terms. The symmetric operation — selecting multiple columns and setting a governance field value across all of them at once (e.g. marking 10 columns as CDE, or setting a shared business domain) — does not exist. It would reuse the existing selection mode infrastructure in `data_contract.js`.

**Open questions:**
- Which governance fields should be bulk-settable?
- Should the bulk edit open a modal to enter the new value, or use a quick-pick dropdown in the toolbar?
- Should bulk edit write directly to `data_column_chars` (same path as single-column governance edits) or go through the YAML?

---

### 9. Run Contract Tests from the Contract Page

There is no way to trigger a test run scoped to the contract's included suites from within the contract page. Users must navigate to the test suites view to kick off execution. A "Run Contract Tests" action that launches execution for all `include_in_contract = TRUE` suites for the table group would close the loop between viewing contract health and acting on it.

**Open questions:**
- Should the run be synchronous (show a spinner) or fire-and-forget with a status banner?
- Should it run all included suites, or let the user pick which suites to run?
- Reuse the existing `testgen run-tests` CLI path or add a contract-scoped wrapper?

---

### 10. Contract Compliance Notifications

When a saved contract's test results degrade — tests that were passing begin failing after a run — there is no alert. The email notification infrastructure already exists in `testgen/common/notifications/`. A contract-specific notification that fires when `tg_test_failed` or `tg_monitor_failed` goes above zero (relative to the saved version's last-known-good state) would be a low-cost addition.

**Open questions:**
- Should the notification fire after every test run, or only when status transitions from passing to failing?
- Should it reuse the existing `TestRunNotification` template or get its own contract-specific email template?
- Should per-contract notification preferences be stored in `notification_settings` or a new `contract_notification_settings` table?

---

### 11. YAML Session State Staleness Detection

The contract YAML cached in `st.session_state` can silently diverge from the DB if tests are edited from the test suites page in another browser tab during the same session. The existing staleness banner detects saved-version vs. current-TestGen drift, but not session-cache vs. DB drift. A lightweight DB fingerprint check (e.g. comparing the max `last_modified` timestamp of `test_definitions` for the table group against a value captured at page load) could detect this and prompt the user to reload.

**Open questions:**
- How frequently should the fingerprint be checked — on every rerun, or only on explicit user actions (save, run)?
- Should the stale-cache state block saves or just show a warning banner?

---

### 12. Coverage Quality Distinction

The Coverage card currently counts a column as "covered" if it has any non-schema term, including observed DDL terms like `physicalType`. A column with only a data type observed during profiling but no quality assertion is counted as covered. A finer breakdown — "has at least one quality test" vs. "has only schema/governance terms" — would make the coverage metric more meaningful for assessing actual test coverage.

**Open questions:**
- Should the card show two coverage percentages (schema coverage vs. quality coverage), or replace the existing metric with the stricter definition?
- Should the Coverage Matrix also visually distinguish columns with only schema terms from columns with quality tests?
