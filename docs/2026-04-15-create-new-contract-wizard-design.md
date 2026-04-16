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
