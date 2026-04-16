# Create New Contract Wizard — Design Spec

**Date:** 2026-04-15
**Branch:** data-contracts-vibe
**Status:** Approved for implementation

---

## Overview

Replace the **Regenerate** button on the Data Contract page with a **Create New Contract** button that opens a reusable 5-step modal wizard. The wizard allows the user to configure a new contract from scratch — selecting which table group, test suites, tables, and content categories to include.

The wizard is designed to be callable from two contexts:

1. **Data Contract page** (existing) — "Create New Contract" button in the toolbar; the table group is pre-filled and the wizard opens at Step 2.
2. **Contract listing page** (future) — wizard opens at Step 1 so the user picks the table group first.

The wizard always saves as a **new version number**, preserving all prior versions as read-only history. It never overwrites an existing version in place.

---

## Architecture

### Reusable Component

```python
@st.dialog("Create New Contract", width="large")
def create_contract_wizard(
    table_group_id: str | None = None,  # Pre-fill Step 1; None = show Step 1
    current_version: int | None = None, # For version number display in confirm step
) -> None:
    ...
```

- Self-contained `@st.dialog` function in `testgen/ui/views/dialogs/data_contract_dialogs.py`
- Step state stored in `st.session_state` under a wizard-scoped key
- Callable from any page — no assumption about surrounding page state
- When `table_group_id` is provided, the wizard skips Step 1 and shows a locked table group banner at the top with a "Change" link. Clicking "Change" resets the wizard to Step 1 with the table group unlocked and clears any selections made in Steps 2–4.

### Invocation Points

| Location | Call style |
|---|---|
| Data Contract page toolbar | `create_contract_wizard(table_group_id=tg_id, current_version=version_record["version"])` |
| Contract listing page (future) | `create_contract_wizard()` — opens at Step 1 |
| First-time flow (replaces `_render_first_time_flow`) | `create_contract_wizard(table_group_id=tg_id)` — opens at Step 2 |

---

## Wizard Steps

### Step 1 — Table Group
**Icon:** `table_view` (Material Symbols Rounded)
**Shown when:** `table_group_id` is not provided by the caller.
**Skipped when:** Caller provides `table_group_id` — wizard opens directly at Step 2, with a locked banner showing the pre-filled group and a "Change" link.

**UI:**
- Search/filter field at the top
- Radio-select list of all table groups the user has access to
- Each row shows: table group name, project, table count, last profiling date, existing contract count
- Existing contract count shown as a blue badge to communicate that multiple contracts per table group are normal and expected

**Data source:** All table groups accessible to the current user, ordered by name.

---

### Step 2 — Test Suites
**Icon:** `rule`
**Shown:** Always (first visible step when called with a pre-filled table group).

**UI:**
- Checklist of all non-monitor, non-snapshot test suites for the selected table group
- Each row shows: suite name, active test count
- All suites are checked by default
- A footer note: *"Monitor suites are controlled separately in Step 4 → Content."*

**Business rules:**
- Suites with `is_monitor=TRUE` are excluded from this list entirely
- Suites with `is_contract_snapshot=TRUE` are excluded
- At least one suite must be selected to proceed

---

### Step 3 — Tables
**Icon:** `table` (Material Symbols Rounded)

**UI:**
- Search/filter field
- "Select all / None" shortcut link
- Checklist of all profiled tables in the selected table group (from `data_column_chars`)
- Each row shows: table name, number of active tests targeting it (0 is valid — schema-only tables are included per design decision)
- All tables are checked by default
- Row count shown above the list: *"12 tables · 10 selected"*

**Business rules:**
- Table list sourced from `data_column_chars` for the table group — all profiled tables, regardless of whether tests exist
- Deselected tables are excluded from both the schema section and any quality rules that target them in the YAML output
- Tests that reference multiple tables (e.g. `Aggregate_Balance`) are included if their **primary table** (`table_name` on the test definition) is in the selected set
- At least one table must be selected to proceed

---

### Step 4 — Content
**Icon:** `tune`

**UI:**
- Four independent on/off toggles, all **on by default**
- Each toggle has an icon (from existing data contract icon set), a label, and a one-sentence description

| Toggle | Icon | Default | Description |
|---|---|---|---|
| Profiling | `data_thresholding` | On | Schema stats (min/max, lengths, format, logical type) in the schema section, plus auto-generated profiling tests in the quality section |
| DDL Constraints | `account_balance` | On | Column data types, NOT NULL, and primary key constraints from the physical database schema |
| Hygiene | `fact_check` | On | Data quality anomalies surfaced by the latest profiling run (definite, likely, possible) |
| Monitors | `sensors` | On | Freshness, volume, schema drift, and metric trend tests from all monitor suites for the selected table group |

**Business rules:**
- The Monitors toggle is fully independent of Step 2 suite selection — it includes all `is_monitor=TRUE` suites for the table group when on
- Turning off Profiling suppresses `_customProperties.testgen.*` stat fields from the schema section and excludes tests where `last_auto_gen_date IS NOT NULL AND lock_refresh = FALSE`
- Turning off DDL Constraints suppresses `physicalType`, `required`, and `_customProperties.testgen.primaryKey` from the schema section
- Turning off Hygiene suppresses anomaly-sourced profiling terms from the contract
- Turning off Monitors excludes all tests from monitor suites

---

### Step 5 — Confirm
**Icon:** `contract`

**UI:**
- Read-only summary card showing all choices made in Steps 1–4:
  - Table group name (with `table_view` icon)
  - Selected suites (with `rule` icon)
  - Table count summary: *"10 of 12 selected"* (with `table` icon)
  - Content categories as a dot-separated string: *"Profiling · DDL · Hygiene · Monitors"* (with `tune` icon)
  - **Tests in scope** count in green (with `bolt` icon) — computed via a DB query on entering Step 5, using the selected suite IDs, table names, and monitor toggle state
- Optional free-text **Contract name** field (stored as the version label)
- **Generate & Save** button (green, primary)

**Business rules:**
- Version number displayed as: current version + 1 (or 1 if no prior versions)
- "Tests in scope" count is computed via a DB query on entering Step 5: active tests from the selected suites where `table_name = ANY(:selected_tables)`, plus active monitor tests for the table group if the Monitors toggle is on
- On confirm: calls the existing `_capture_yaml` / `save_contract_version` / `create_contract_snapshot_suite` pipeline, passing the new filter parameters
- On failure of snapshot suite creation, rolls back the saved version (same rollback logic as current `_regenerate_dialog`)

---

## Step Indicator

A compact horizontal indicator inside the dialog header area:

```
[pill: N · Step Name]  •  •  •     Step N of 5
```

- **Current step:** Colored pill containing the step's icon + number + name
  - Dark mode: `#89b4fa` background, `#1e2130` text
  - Light mode: `#1e66f5` background, `#ffffff` text
- **Completed steps:** Small filled dots (green: `#a6e3a1` dark / `#16a34a` light)
- **Upcoming steps:** Small unfilled dots (gray: `#313244` dark / `#dce1e9` light)
- **"Step N of 5"** counter right-aligned

This replaces the 5-circle-with-labels layout, which is too wide for dialog widths with 5 steps.

---

## Light & Dark Mode

All colors follow the existing TestGen theme palette:

| Element | Dark | Light |
|---|---|---|
| Dialog background | `#1e2130` | `#ffffff` |
| Step body panel | `#2a2d3e` | `#f5f7fb` |
| Row item background | `#1e2130` | `#ffffff` with `#e8eaf0` border |
| Selected row | `#1a2640` + `#89b4fa` border | `#eef3ff` + `#1e66f5` border |
| Primary accent | `#89b4fa` | `#1e66f5` |
| Heading accent | `#cba6f7` | `#7c3aed` |
| Toggle on | `#1e3a5f` bg, `#89b4fa` text | `#dbeafe` bg, `#1e66f5` text |
| Success / generate | `#a6e3a1` | `#16a34a` |
| Muted text | `#6c7086` | `#8c8fa3` |

Icons use **Material Symbols Rounded** — the same font and ligature names already loaded by the existing data contract component.

---

## Export Filter Parameters

The existing `export_data_contract.py` export pipeline must be extended to accept filter parameters. New signature:

```python
def run_export_data_contract(
    table_group_id: str,
    output_path: str | None = None,
    output_stream: io.StringIO | None = None,
    # New filter parameters:
    suite_ids: list[str] | None = None,       # None = all included suites
    table_names: list[str] | None = None,     # None = all profiled tables
    include_profiling: bool = True,
    include_ddl: bool = True,
    include_hygiene: bool = True,
    include_monitors: bool = True,
) -> None:
```

When `suite_ids` is provided, only those suites are queried (replacing the `include_in_contract IS NOT FALSE` filter).
When `table_names` is provided, schema and quality queries are filtered to those tables via a `WHERE table_name = ANY(:table_names)` clause.

---

## What Replaces What

| Before | After |
|---|---|
| **Regenerate** button → `_regenerate_dialog()` | **Create New Contract** button → `create_contract_wizard()` |
| `_render_first_time_flow()` — inline page wizard | `create_contract_wizard(table_group_id=tg_id)` — same modal, opens at Step 2 |
| No table/suite/content filtering on export | Filtered export via new `run_export_data_contract` parameters |

The `_regenerate_dialog` function can be deleted. `_render_first_time_flow` is replaced by a call to the modal wizard — the wizard never blocks on prereqs, but surfaces warnings contextually:

- **Step 2 (Suites):** If no non-monitor suites exist for the table group, an inline warning is shown and Next is disabled.
- **Step 4 (Content):** If no completed profiling run exists for the table group, the Profiling toggle shows an inline warning ("No profiling data — profiling stats will be empty") but remains toggleable.
- **Step 5 (Confirm):** If "Tests in scope" resolves to 0, the Generate & Save button is disabled with an explanation.

---

## Testing

### Unit Tests
**Location:** `tests/unit/ui/test_contract_wizard.py`
**Marker:** `@pytest.mark.unit`
**Pattern:** Mock all `st.*` calls via monkeypatch (same pattern as `test_contract_dialog_warnings.py`). No Streamlit runtime required.

| Test | What it verifies |
|---|---|
| `test_step_advances_on_next` | Clicking Next increments the step counter in session state |
| `test_back_decrements_step` | Clicking Back decrements the step counter; cannot go below 1 |
| `test_step1_skipped_when_tg_provided` | When `table_group_id` is passed, wizard initialises at step 2 |
| `test_change_link_resets_to_step1` | Clicking "Change" on the pre-filled banner sets step to 1 and clears suite/table/content selections |
| `test_step2_next_disabled_with_no_suites` | Next is disabled when no suites are checked |
| `test_step2_excludes_monitor_suites` | `is_monitor=TRUE` suites do not appear in the Step 2 checklist |
| `test_step2_excludes_snapshot_suites` | `is_contract_snapshot=TRUE` suites do not appear |
| `test_step3_next_disabled_with_no_tables` | Next is disabled when all tables are deselected |
| `test_step3_select_all_none` | "Select all" checks all; "None" unchecks all |
| `test_step3_multi_table_test_included_on_primary` | A test whose `table_name` is in the selected set is included even if its secondary reference table is deselected |
| `test_step4_monitors_toggle_independent` | Monitors toggle state is independent of Step 2 suite selection |
| `test_step4_profiling_warning_when_no_profiling_run` | Profiling toggle shows warning text when `last_profiling` is None |
| `test_step5_generate_disabled_when_zero_tests` | Generate & Save button is disabled when in-scope test count is 0 |
| `test_step5_version_number_increments` | Displayed version = `current_version + 1`; version = 1 when no prior versions |
| `test_export_filter_params_constructed_correctly` | `run_export_data_contract` is called with the correct `suite_ids`, `table_names`, and content booleans derived from wizard state |
| `test_rollback_on_snapshot_suite_failure` | If `create_contract_snapshot_suite` raises, `rollback_contract_version` is called with the new version number |

**Supporting unit tests for the extended export pipeline:**
**Location:** `tests/unit/commands/test_export_data_contract_filters.py`

| Test | What it verifies |
|---|---|
| `test_suite_filter_restricts_quality_query` | Passing `suite_ids` excludes tests from suites not in the list |
| `test_table_filter_restricts_schema_and_quality` | Passing `table_names` excludes schema rows and quality rules for excluded tables |
| `test_include_profiling_false_strips_stat_fields` | Schema properties omit `customProperties.testgen.*` stat fields when `include_profiling=False` |
| `test_include_ddl_false_strips_ddl_fields` | Schema properties omit `physicalType`, `required`, `primaryKey` when `include_ddl=False` |
| `test_include_monitors_false_excludes_monitor_tests` | Monitor suite tests absent from quality section when `include_monitors=False` |
| `test_no_filters_produces_same_output_as_current` | Calling with all defaults produces identical output to the current unfiltered export |

---

### Functional / AppTest Tests
**Location:** `tests/functional/ui/test_contract_wizard_apptest.py`
**App scripts:** `tests/functional/ui/apps/contract_wizard_*.py` (one script per scenario)
**Marker:** `@pytest.mark.functional`
**Pattern:** `AppTest.from_file(script, default_timeout=15)` — same pattern as `test_data_contract_apptest.py`. Each script bootstraps minimal mocked DB state and renders the wizard directly.

| Test | App script | What it verifies |
|---|---|---|
| `test_wizard_full_flow_from_listing_page` | `contract_wizard_full_flow.py` | Step 1 shown; user selects table group, advances through all steps, clicks Generate & Save; success path completes without error |
| `test_wizard_skips_step1_when_tg_provided` | `contract_wizard_prefilled_tg.py` | Wizard renders at Step 2 when `table_group_id` is pre-filled; "Change" link visible |
| `test_wizard_change_link_returns_to_step1` | `contract_wizard_prefilled_tg.py` | Clicking the "Change" link renders the table group picker (Step 1) |
| `test_wizard_step2_no_suites_warning` | `contract_wizard_no_suites.py` | Step 2 shows a warning and Next button is disabled when table group has no eligible suites |
| `test_wizard_step4_profiling_warning_no_profiling` | `contract_wizard_no_profiling.py` | Step 4 Profiling toggle shows the "no profiling data" warning text |
| `test_wizard_step5_disabled_when_zero_tests` | `contract_wizard_zero_tests.py` | Step 5 Generate & Save button is disabled; explanatory text is shown |
| `test_wizard_replaces_first_time_flow` | `contract_wizard_first_time_flow.py` | Data Contract page with no saved contract renders the wizard modal trigger instead of the old inline prereqs flow |

---

## Out of Scope

- Editing an existing contract's scope after creation (change which tables/suites are included) — this is a separate feature
- Per-table content toggle granularity (e.g. profiling on for table A, off for table B)
- Contract naming / renaming outside of the version label field
- Validation of ODCS YAML correctness before saving (existing behavior unchanged)

---

## UI Mockups

Mockups saved in `.superpowers/brainstorm/` — both light and dark mode, all 5 steps:
- `wizard-light-dark-v3.html` — final approved mockup (Steps 1, 2, 4, 5 in both themes)
- `wizard-steps-v3.html` — full 5-step flow in dark mode with all step content

Reference: `http://localhost:50723` (local brainstorm server, session-scoped)
