# Data Contract — Design

> Last updated: 2026-04-06 (UI polish: modal headers, governance metadata, PII model, YAML description/severity, Regenerate button)

---

## 1. What This Is

A Data Contract in TestGen is a **saved snapshot** of a Table Group's quality configuration: its schema, governance metadata, and active test suite definitions, captured at a point in time and assigned a version number.

The contract answers two questions:
1. *"What did we agree this data product looks like at version N?"*
2. *"Has anything changed since we saved that agreement?"*

The underlying data — profiling results, test runs, anomalies — is always changing. The contract is deliberately **not live**. It is a saved document that the system compares against current state to surface drift.

---

## 2. The Versioning Model

- A table group can have multiple saved contract versions.
- Version numbers are **integers starting at 0**, auto-incremented by 1 on each save. The first save produces version 0, the next version 1, and so on.
- Each version carries a **save timestamp** (date and time). That timestamp is the primary way versions are identified to the user — the integer is the stable unique key behind the scenes.
- The **latest saved version** is what the user sees by default.
- Saving a new version preserves all history — old versions are never deleted.
- Users can optionally add a label to each version (e.g. "Added PII tests for orders table").
- There is no lifecycle state machine (no draft/active/deprecated). A version is either the latest or superseded.
- Version auto-increment is implemented as a single atomic `INSERT ... SELECT MAX(version)+1` statement, not a separate SELECT followed by an INSERT. This prevents a race condition where two simultaneous saves for the same table group both read the same max and attempt to write duplicate version numbers. The `UNIQUE(table_group_id, version)` constraint is a safety net but should never be triggered under normal operation.

### Staleness

After a contract is saved, the system detects **drift** by comparing the snapshot against live data. The contract is marked stale when any of the following occur after the save date:

| Signal | Meaning |
|---|---|
| A profiling run completes | Schema, types, or observed statistics may have changed |
| A test definition is added, changed, or removed | Quality claims no longer match what is being tested |
| A column is added or dropped | The schema section is stale |
| A test suite is added, removed, or its in-contract toggle changes | The scope backing the contract has changed |

Staleness is a **warning, not a lock**. The saved contract remains viewable and downloadable. The user is shown what changed and prompted to review and re-save.

---

## 3. Page Layout

The Data Contract page lives at `?table_group_id=<uuid>`. It is reached from the Table Group list, Project Dashboard, and Data Catalog.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Breadcrumb: Table Groups › orders_group › Data Contract            │
│                                                                     │
│  ◆ orders_group         3  ·  Commerce  ·  orders  ·  PostgreSQL   │
│  Primary order transaction data for the Commerce domain…            │
│                                          [Refresh] [Download YAML]  │
│  [⚠ Stale — 2 new columns, 1 threshold changed.  Review · Save 4]  │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  Coverage    │  │  Test Health │  │  Hygiene     │              │
│  │  87%  ████░  │  │  34 tests    │  │  5 issues    │              │
│  │  52/60 cols  │  │  ██░░░ bar   │  │  1 def 2 lkly│              │
│  │  View 8 →   │  │  View 2 fail │  │  View 5 →    │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
├─────────────────────────────────────────────────────────────────────┤
│  Overview │ Coverage Matrix │ YAML                                  │
├─────────────────────────────────────────────────────────────────────┤
│  [Gap Analysis summary card — 1 error · 2 warnings]                │
│                                                                     │
│  Claims Detail              Filter: [All] [Failing] [Uncovered]    │
│                                                                     │
│  ▼ orders  (4 columns)                                              │
│    order_id    INTEGER    🔑 PK                                     │
│      [DDL: INTEGER NOT NULL 🏛️] [Profiling: Unique·10k 📸]         │
│      [Test: ✅ Row_Ct ≥ 1000 ⚡]                                    │
│                                                                     │
│    customer_id INTEGER    PII                                       │
│      [DDL: INTEGER NOT NULL 🏛️] [Gov: Classification: PII 🏷️]      │
│      ⚠ No test — PII unguarded                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Page Header

The header shows the table group name, version number, and key metadata as dismissable pills:

- Version (e.g. `3`)
- Domain
- Data product name
- Database flavor
- Schema path

Below the title is the table group's description/purpose text.

Action buttons:
- **Refresh** — reload the saved contract from the database and clear any pending in-memory edits. If there are unsaved changes, a confirmation dialog warns before discarding them. Does not create a new version.
- **Download YAML** — download the currently displayed contract version as ODCS YAML

### Staleness Banner

When the contract is stale, a banner appears below the header (dismissible per session):

```
⚠ This contract (version 3) was saved on Mar 15, 2026.
  Since then: 2 new columns detected, 1 test threshold changed, profiling ran Apr 1.
  [Review Changes]  [Dismiss]
```

"Review Changes" opens a diff panel showing exactly what changed column by column. The save action is available only inside the diff panel — after the user has seen what changed — to prevent blind saves of an unexpected state. "Dismiss" hides the banner for the session only.

---

## 5. First-Time Flow (No Saved Contract)

When a table group has no saved contract, the page shows a guided generation flow instead of the normal layout.

### Step 1 — Prerequisites check

```
┌─────────────────────────────────────────────────┐
│  ◆ orders_group — No contract yet               │
│                                                 │
│  To generate a contract we need:                │
│                                                 │
│  ✅ Profiling run complete       (Apr 1, 2026)  │
│  ✅ At least one test suite      (3 suites,     │
│     34 active tests — monitor suites excluded)  │
│  ⚠  Column metadata sparse      (12% coverage) │
│     Descriptions and PII flags improve          │
│     contract quality — you can add them later.  │
│                                                 │
│                      [Generate Contract →]      │
└─────────────────────────────────────────────────┘
```

Profiling and at least one non-monitor test suite with at least one active test are **required**. Monitor suites (`is_monitor = TRUE`) are always excluded from the contract and do not count toward this requirement. Column metadata (descriptions, PII flags, CDE flags) is **recommended** but not blocking — the user can proceed and add metadata later.

If profiling hasn't run, show a link to the Run Profiling page. If no qualifying test suites exist, link to Test Suites.

### Step 2 — Preview

Generate a preview contract from the current state and show:

- Coverage score (% of columns with at least one non-schema claim)
- Total tables and columns
- Number of quality tests that will be included
- Gap analysis summary (errors and warnings)

The full Claims Detail view is available to browse before saving.

### Step 3 — Save as Version 0

User adds an optional label, then saves. The contract is stored as version 0 with the save timestamp. The page transitions to the normal contract view.

---

## 6. Health Dashboard

Three metric cards sit above the tab bar. Each card also acts as a filter shortcut for the Claims Detail view below.

### Coverage card

- Large percentage number (e.g. `87%`) colored green / orange / red
- Progress bar fill
- Sub-label: "52 of 60 columns have ≥1 non-schema claim"
- Button: "View 8 uncovered →" — activates the `uncovered` filter on Claims Detail

A column counts as **covered** when it has at least one claim beyond the physical type and nullability: a classification, CDE flag, description, format pattern, or an active test.

Color thresholds: green ≥ 80%, orange ≥ 50%, red < 50%.

### Test Health card

- Total test count as the headline number
- Horizontal segmented bar: green (passed) / yellow (warning) / red (failing) / gray (not run)
- Count breakdown below the bar
- Button: "View 2 failures →" — activates the `failing` filter

### Hygiene card

- Issue count as the headline (e.g. `5 issues`)
- Counts broken down by Definite / Likely / Possible
- Button: "View 5 anomalies →" — activates the `anomalies` filter

---

## 7. Tabs

### Overview (default)

Shows the Gap Analysis summary card followed by the Claims Detail section. This is the primary working view.

The Gap Analysis summary card on this tab shows only the total counts (e.g. "1 error · 2 warnings"). It is a navigation aid — the full gap list is not a separate tab but can be reached from the cards.

### Coverage Matrix

A compact table with one row per column across all tables in the contract. The **ClaimCountsBar** sits at the top of this tab, showing total claim counts broken out by source (DDL / Profiling / Governance / Test) and by verification tier (DB Enforced / Tested / Monitored / Observed / Declared).

Below the bar, each table is a collapsible accordion section. When collapsed, the header shows the table name on the left and — right-justified — counts for each of the 5 tier columns.

Each table section has one row per column plus one `(table-level)` row when table-level rules exist (e.g. monitor rules with `element = table_name`). The 5 tier columns are:

| Column | Icon | What counts |
|---|---|---|
| DB Enforced | 🏛️ | Physical type claim (always 1 per column) |
| Tested | ⚡ | Non-monitor active test definitions |
| Monitored | 📡 | Monitor rules (Freshness_Trend, Volume_Trend, Schema_Drift, Metric_Trend) |
| Observed | 📸 | Profiling stats: min/max, row count, uniqueness, format pattern, logical type |
| Declared | 🏷️ | Governance annotations: classification, CDE flag, description |

The grand-total row at the bottom of the matrix shows "All tables" on the left and all tier totals right-justified.

**Claim count consistency invariant**: the grand total in the Coverage Matrix must equal the ClaimCountsBar total (by source) and the ClaimCountsBar total (by verification tier), both of which must equal the total shown in the Claims Detail accordion header. This is enforced by unit tests in `Test_ClaimCountConsistency`.

### YAML

The full ODCS v3.1.0 YAML of the saved contract, rendered with syntax highlighting. A "Copy" button and "Download" button sit at the top right. This view is read-only — edits happen through the claims UI, not raw YAML editing.

---

## 8. Claims Detail

The main body of the Overview tab. Shows all tables and their columns, each with its set of claims laid out as chips in a horizontal row.

### Layout

```
Claims Detail (247 total)          Filter: [All] [Failing] [Uncovered]

▼ orders  (12 columns)  ·  3 table-level

  Table-level
    [Test: ✅ Row_Ct ≥ 10,000 ⚡]

  order_id    INTEGER    🔑 PK
    [DDL: INTEGER NOT NULL 🏛️]  [Profiling: Unique · 10,432 rows 📸]
    [Test: ✅ Row_Ct ≥ 1000 ⚡]

  customer_id  INTEGER   PII
    [DDL: INTEGER NOT NULL 🏛️]  [Gov: Classification: PII 🏷️]
    ⚠ No test — PII unguarded

  order_date   DATE      CDE
    [DDL: DATE 🏛️]  [Profiling: Range 2022–2026 📸]
    [Test: ⚠️ Freshness ≤ 2d ⚡]   ⚠ Stale 3d ago

  total_amount  NUMERIC(12,2)
    [DDL: NUMERIC(12,2) 🏛️]  [Profiling: Min 0.01 · Max 48,200 📸]
    [Test: ✅ Avg ∈ [0.95, 1.05] ⚡]
```

**Table-level claims** are tests or annotations that apply to the whole table rather than a specific column — typically row count, freshness, or referential integrity. They appear in a "Table-level" sub-section above the column rows within each table block.

Each table is a collapsible section. The first table opens by default; the rest are collapsed.

**Collapsed accordion header format** (using `ts-name` / `ts-meta` CSS pattern):
- Left (`ts-name`): table name
- Right (`ts-meta`): column count · N table-level claims · N column-level claims

All metadata in the header is right-justified. The column count and claim counts make the closed header scannable without expanding.

### Claim chips

Each chip shows three things:
- **Source label** (small, uppercase): DDL / Profiling / Governance / Test
- **Value**: the human-readable fact
- **Verification badge**: 🏛️ DB Enforced / ⚡ Tested / 📡 Monitored / 📸 Observed / 🏷️ Declared

Chip border and background color encodes the source:
- DDL → purple tint
- Profiling → blue tint
- Test → green tint
- Governance → amber tint

Live test chips additionally show a status pill (passing / warning / failing / not run).

Clicking a chip opens a detail dialog. For governance claims (Classification, CDE, Description) the dialog has an edit mode. For test claims the dialog shows the last result and links to the test definition.

### Filters

Six filter buttons at the top of the Claims Detail section:
- **All** — shows everything
- **DB Enforced** — shows only `db_enforced` claims
- **Tested** — shows only `tested` claims
- **Monitor** — shows only `monitored` claims
- **Observed** — shows only `observed` claims
- **Declared** — shows only `declared` claims

Filtering **strips non-matching claims from within each column** — it does not merely hide columns. A column row with no matching claims is hidden entirely. Filters activated from the health dashboard cards set these automatically and vice versa — they share the same state.

---

## 9. Editing Claims

Only two claim sources are editable in-place:

**Governance claims** (Classification, CDE, Description):
- Click the chip → dialog opens with the current value and an edit field
- Clicking Apply in the dialog holds the change **in memory only** — nothing is written to the DB yet
- The chip updates visually on the page to reflect the pending value
- The **"Save new version"** button is **always visible** on the latest version (right-aligned, secondary style). When there are pending changes it shows a dirty indicator: `Save new version ● (N)` and a tooltip listing the pending fields
- All pending changes are written to `data_column_chars` atomically when the user saves a new contract version

**Test claims** (threshold, tolerance, description, severity):
- Click the chip → dialog shows last result and an edit form for the threshold
- Same pending-state model: held in memory, written to `test_definitions` on version save

**Navigating away with unsaved changes** shows a confirmation dialog ("Leave without saving? 1 unsaved change will be lost"). Choosing to leave discards all pending in-memory edits.

All other claims (DDL, Profiling) are read-only. DDL facts come from the physical schema; profiling facts come from the last profiling run. They cannot be overridden here.

---

## 10. Coverage Tiers

Every column is assigned one or more tiers that describe how its claims are enforced. These appear as the 5 columns of the Coverage Matrix and as verification badges (🏛️ ⚡ 📡 📸 🏷️) on individual claim chips.

| Tier | Badge | How earned |
|---|---|---|
| DB Enforced 🏛️ | purple | The column has a physical type (integer, varchar, date, etc.) — always 1 per column |
| Tested ⚡ | green | At least one non-monitor active test definition references this column or table |
| Monitored 📡 | orange | A monitor rule applies to this element — exclusively `Freshness_Trend`, `Volume_Trend`, `Schema_Drift`, or `Metric_Trend` test types. Profiling anomalies are **not** monitored; they are **observed**. |
| Observed 📸 | gray | Profiling captured stats: row count, uniqueness, min/max values, format pattern, logical type, string length distributions |
| Declared 🏷️ | amber | A governance annotation exists: classification, CDE flag, or description |

**Important**: "Monitored" means only the four `_MONITOR_TEST_TYPES` above (`_MONITOR_TEST_TYPES = {"Freshness_Trend", "Volume_Trend", "Schema_Drift", "Metric_Trend"}`). Profiling anomaly results from `profile_anomaly_results` are sourced as `profiling` / `observed`. The badge icon for Monitored was changed from 🔬 to 📡.

**Table-level monitor rules**: Monitor rules have `element = table_name` (no column suffix), so they appear in a `(table-level)` row in the Coverage Matrix rather than in a column row. The collapsed accordion header always shows the monitored count so table-level monitors are not invisible when the section is collapsed.

**ClaimCountsBar source mapping**: The "by source" breakdown uses `{ddl, profiling, governance, test}`. Monitor rules are categorized under `test` (not a separate `monitor` bucket) because monitors are implemented as test definitions. The "by verification" breakdown uses `{db_enforced, tested, monitored, observed, declared}`.

---

## 11. Technical Notes

### What is stored in a saved contract

The saved snapshot (`data_contracts.contract_yaml`) captures:
- Schema section: column names, physical types, nullability, PK/FK, observed stats
- Governance: classification, CDE flags, descriptions
- Quality rules: test definitions with thresholds and operators
- References: foreign key relationships
- SLA: declared latency (profiling delay days)
- Suite scope: which suites were included at save time

The snapshot does **not** capture live data that changes continuously:
- Test results (`lastResult`) — always fetched fresh from `test_results`
- Compliance summary — computed at render time from live results
- Test run history — fetched fresh from `test_runs`
- Profiling anomalies — fetched fresh from `profile_anomaly_results`

This means the same saved contract snapshot shows different live health depending on when it is viewed, which is the intended behavior.

When viewing a **historic version** (not the latest), test result overlays and anomaly counts are still live. The hygiene card must display a caption — "Anomalies are always current — not from this snapshot" — to prevent the user from interpreting today's anomalies as the state at save time.

### Edit persistence model

Claim edits made in the UI are held in memory (Streamlit session state) until the user explicitly saves a new version. Two session keys work together and must stay in sync:

- **`dc_yaml:{table_group_id}`** — the in-memory YAML doc, patched in place as each edit is applied. This is the rendering source of truth.
- **`dc_pending:{table_group_id}`** — the list of pending edits. Drives the dirty button and the save dialog summary.

Every "Apply" click in an edit dialog must patch both keys before triggering a rerun. `dc_yaml` must never be cleared (reloaded from DB) while `dc_pending` is non-empty, as doing so would discard the pending overlay.

On version save, the sequence is:
1. Write governance pending edits → `data_column_chars`
2. Write test pending edits → `test_definitions`
3. Build the snapshot YAML from the current in-memory patched doc — **not** from a fresh export. A fresh export at save time would pull in new anomalies or test results that occurred after the user began editing, producing a snapshot that doesn't match what the user reviewed and approved.
4. Call `save_contract_version(table_group_id, snapshot_yaml, label)`
5. Clear both session keys; next render loads the newly saved version from DB.

There is no intermediate "draft" state in the DB — edits either land with a version save or are discarded.

### YAML format

The snapshot is stored as ODCS v3.1.0 YAML. The ODCS lifecycle `status` field is not used. The `team.members` list is always empty (member schema is not yet defined).

### Staleness detection

`table_groups.contract_stale` is set to `TRUE` when:
- A profiling run completes with `profiling_starttime > last_contract_save_date` — this is also the signal for schema drift (column adds, drops, type changes), since column metadata is refreshed during profiling
- Any `test_definitions` row for the table group is inserted, updated, or deleted
- Any `test_suites.include_in_contract` is toggled for the table group

Schema drift (columns added or dropped in the source database) is detected via the profiling run trigger. A column change will not mark the contract stale until profiling reruns. This is acceptable near-term; a DDL-watch trigger could catch changes immediately in a future iteration.

### Suite scope

Individual test suites can be excluded from the contract via `include_in_contract = FALSE`. Monitor suites (`is_monitor = TRUE`) are always excluded. The suite picker dialog lets the user drill into a specific suite's results when the contract covers multiple suites.

### Modal architecture

All dialogs use the `emitEvent` + `@st.dialog` pattern. The VanJS component iframe clips `position: fixed/absolute` elements — dialogs cannot be rendered inside the iframe. All overlays must route through:

```
JS: emitEvent("ClaimDetailClicked", { claim, tableName, colName })
  → Python event_handlers["ClaimDetailClicked"]
  → @st.dialog renders
```

Use `event_handlers` (not `on_change_handlers`) for any handler that calls `st.rerun()`.

### Modal header design

All five claim/governance dialogs share `_modal_header(verif, name, table_name, col_name, subtitle="")`:
- **Line 1 (bold, 17px):** `{icon} {verif_label} — {name}` — e.g. `⚡ Tested — Null Check`
- **Line 2 (caption, monospace):** `table_name · col_name` on a single line
- **Optional subtitle:** test type description shown below the divider

| Dialog | `verif` key | `name` |
|---|---|---|
| `_test_claim_dialog` | `"tested"` | `test_name_short` from `test_types` |
| `_monitor_claim_dialog` | `"monitored"` | monitor rule name |
| `_claim_read_dialog` | from `claim["verif"]` | claim name |
| `_claim_edit_dialog` | `"declared"` | claim name |
| `_governance_edit_dialog` | `"declared"` | `"Governance Metadata"` |

### Governance metadata

- Sourced live from `data_column_chars` on every render — NOT from the cached YAML
- `_fetch_governance_data(table_group_id)` returns `{(table_name, col_name): dict}`
- One claim chip per populated field: Critical Data Element, Excluded Data Element, PII, Description, Data Source, Source System, and 8 tag fields
- **PII model is binary**: any truthy `pii_flag` = PII. Stored as `"MANUAL"` when set, `NULL` when cleared. Display always shows `"Yes"`. Edited via a simple checkbox ("Contains PII").
- SQL: use `CAST(:col_id AS uuid)` — never `::uuid` (conflicts with SQLAlchemy `:param` binding)

### YAML quality rule fields

Each rule in `quality:` includes:
- `name` — user's `test_description` from `test_definitions`, falling back to `test_name_short`
- `description` — `test_types.test_description` (system explanation) combined with user notes if both present
- `severity` — from `test_definitions.severity`, defaults to `"error"`

### Regenerate contract

`_regenerate_dialog(table_group_id, current_version)` — opens via **↺ Regenerate** button in toolbar (latest version only). Re-runs `_capture_yaml` → `run_export_data_contract` and immediately calls `save_contract_version`. Use this to pick up schema/test/governance changes that post-date the last saved version.

### HTML escaping

All user-sourced strings rendered inside claim cards (descriptions, classification values, test threshold expressions) must be escaped with `html.escape(value, quote=True)`. Do NOT use manual `.replace("<", "&lt;")` chains — they miss `&`, `"`, and `'`.

### Logging

Use `LOG = logging.getLogger(__name__)` consistently throughout `data_contract.py`. Do not mix `LOG` and `_log`. Silent exception swallowing (bare `except: pass` or `except: return`) must log at `WARNING` level with `exc_info=True` before returning.

### SQL safety

Never f-string-interpolate UUIDs or user-supplied values into SQL. Use parameterized queries (`%s` placeholders with a parameters tuple) even for UUID values such as `table_group_id`. This applies to `_fetch_anomalies` and all other query helpers in `data_contract.py`.

### Shared utilities

`_pii_flag_to_classification(pii_flag: str) -> str` lives in `export_data_contract.py` and is imported by `contract_staleness.py`. Do not duplicate PII mapping logic in both files.

---

## 12. User Flows

---

### Flow A — No contract exists: creating the first one

**Entry point:** User clicks "Data Contract" from the Table Group list for a table group that has never had a contract saved.

```
Table Group List
  orders_group   [Profile] [Test] [Data Contract]
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│  ◆ orders_group  ·  Data Contract                               │
│                                                                 │
│  No contract saved yet.                                         │
│                                                                 │
│  Before we can generate a contract we need:                     │
│                                                                 │
│    ✅  Profiling run complete     last run Apr 1, 2026           │
│    ✅  At least one test suite    3 suites, 34 active tests      │
│                                   (monitor suites excluded)      │
│    ⚠   Column metadata sparse    11% of columns have            │
│         descriptions or PII flags. You can add these now or     │
│         later — they improve contract coverage.                  │
│                                                                 │
│                           [Generate Contract Preview →]         │
└─────────────────────────────────────────────────────────────────┘
```

If profiling has never run, the ✅ becomes a ❌ with a link to the Run Profiling page. The Generate button is disabled until both required items are green.

User clicks **Generate Contract Preview →**

```
┌─────────────────────────────────────────────────────────────────┐
│  ◆ orders_group  ·  Contract Preview  (not yet saved)           │
│                                                                 │
│  Coverage  72%  ████████░░                                      │
│  43 of 60 columns have ≥1 non-schema claim                      │
│                                                                 │
│  Test Health  34 tests  ·  26 ✅  3 ⚠  2 ❌  3 ⏳               │
│                                                                 │
│  Gaps found:                                                    │
│    ❌  orders.customer_id  is PII with no quality test           │
│    ⚠   orders.order_date   is a CDE with no test                │
│    ⚠   order_items         table has no tests at all            │
│                                                                 │
│  You can save now and fix gaps later, or go to Test Suites      │
│  to add tests first.                                            │
│                                                                 │
│  Label (optional): [________________________]                   │
│                                                                 │
│  [← Back]                    [Save as Version 0]               │
└─────────────────────────────────────────────────────────────────┘
```

The full Claims Detail tab is available here for browsing — the user can see exactly what will be in the contract before committing. Gaps are shown but do not block saving.

User types an optional label and clicks **Save Version 0**.

```
┌─────────────────────────────────────────────────────────────────┐
│  ◆ orders_group  ·  Data Contract  ·  0  ·  Apr 5, 2026 09:14  │
│  "Initial contract"                                             │
│                             [Refresh]  [Download YAML]          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ Coverage 72% │  │ 34 tests     │  │ 5 hygiene    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│  Overview │ Coverage Matrix │ YAML                                │
│  …                                                              │
└─────────────────────────────────────────────────────────────────┘
```

The contract is now saved. The page transitions to the normal view showing version 0 as the latest.

---

### Flow B — Viewing a historic contract version

**Entry point:** User is on the Data Contract page viewing the latest version (3) and wants to look back at what version 1 looked like.

The version indicator in the header is a clickable dropdown showing the integer version and save timestamp:

```
┌─────────────────────────────────────────────────────────────────┐
│  ◆ orders_group  ·  Data Contract  ·  [3  Apr 5 09:14 ▾]  …    │
│                         ┌──────────────────────────────────┐    │
│                         │  3  Apr 5  09:14  "PII fix"      │    │
│                         │  2  Mar 15 14:22  ─────────────  │    │
│                         │  1  Feb 28 11:05  "Q1 review"    │    │
│                         │  0  Jan 10 08:30  "Initial"      │    │
│                         └──────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

User selects **version 1**.

```
┌─────────────────────────────────────────────────────────────────┐
│  ◆ orders_group  ·  Data Contract  ·  [1  Feb 28 11:05 ▾]  …   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  📋 Viewing version 1 — saved Feb 28, 2026 at 11:05     │    │
│  │  "Q1 review"                                            │    │
│  │  This is a read-only snapshot. The latest is version 3. │    │
│  │                              [View Latest →]            │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  [Refresh disabled]  [Download YAML]                            │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ Coverage 61% │  │ 22 tests     │  │ 5 hygiene    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│  Overview │ Coverage Matrix │ YAML                                │
│  …claims rendered from the version 1 snapshot…                  │
└─────────────────────────────────────────────────────────────────┘
```

Key behaviors when viewing a historic version:
- A blue "historical version" banner is pinned below the header.
- The coverage and test health cards reflect the **snapshot at version 1** — not today's live state.
- The hygiene (anomaly) card always shows **live anomalies** from today, not those at save time. A caption on the card reads: "Anomalies are always current — not from this snapshot."
- Live test statuses (lastResult) are still fetched fresh from the DB and overlaid on the version 1 quality rules, so the user can see: "this rule existed in version 1 — is it still passing today?"
- The "Refresh" button and "Save" actions are disabled — you cannot modify a past version.
- "Download YAML" works and produces the version 1 snapshot verbatim.
- Editing chips is disabled with a tooltip: "Switch to the latest version to make edits."

---

### Flow C — Viewing the latest version, making an edit, saving

**Entry point:** User is on the Data Contract page on the latest version (2, saved Mar 15). The contract is current (not stale). They notice that `orders.customer_id` has a wrong classification and want to fix it.

```
┌─────────────────────────────────────────────────────────────────┐
│  ◆ orders_group  ·  Data Contract  ·  2  Mar 15 14:22  (latest) │
│                                          [Refresh] [Download]   │
│  …health cards…                                                 │
│                                                                 │
│  ▼ orders  (12 columns)                                         │
│                                                                 │
│    customer_id   INTEGER   PII                                   │
│      [DDL: INTEGER NOT NULL 🏛️]                                  │
│      [Gov: Classification: confidential 🏷️]  ← user clicks this │
└─────────────────────────────────────────────────────────────────┘
```

Clicking the Governance chip opens a dialog:

```
┌────────────────────────────────┐
│  Edit — Classification         │
│  orders › customer_id          │
│  ─────────────────────────────  │
│  Classification                │
│  [confidential            ▾]   │
│   · public                     │
│   · confidential               │
│   · restricted                 │
│                                │
│  ℹ Changes are held until you  │
│    save a new contract version. │
│                                │
│  [Cancel]         [Apply]      │
└────────────────────────────────┘
```

User changes to `restricted` and clicks **Apply**.

The dialog closes. The chip on the page updates to show `restricted` with a pending indicator. The **Save** button in the header activates to signal unsaved changes:

```
┌─────────────────────────────────────────────────────────────────┐
│  ◆ orders_group  ·  Data Contract  ·  2  Mar 15 14:22  (latest) │
│                      [Refresh]  [Download]  [Save new version ●]│
│                                             ↑                   │
│                             filled/primary style + dot          │
│                             tooltip: "1 unsaved change —        │
│                             orders.customer_id: confidential    │
│                             → restricted"                       │
└─────────────────────────────────────────────────────────────────┘
```

If the user navigates away without saving, a confirmation dialog warns them:

```
┌──────────────────────────────────────┐
│  Leave without saving?               │
│                                      │
│  You have 1 unsaved change.          │
│  If you leave now it will be lost.   │
│                                      │
│  [Stay]          [Leave anyway]      │
└──────────────────────────────────────┘
```

User clicks **Save new version ●**. A save dialog appears:

```
┌────────────────────────────────────────┐
│  Save as Version 3                     │
│                                        │
│  Pending changes:                      │
│    · orders.customer_id classification │
│      confidential → restricted         │
│                                        │
│  Label (optional):                     │
│  [________________________________]    │
│                                        │
│  [Cancel]          [Save Version 3]    │
└────────────────────────────────────────┘
```

On confirm, all pending changes are written to the DB and the snapshot is saved atomically as version 3 with the current timestamp. The button returns to its normal subdued style. The version dropdown now shows version 3 as the latest. Version 2 is preserved in history.

---

### Flow D — A test is added to a test suite; updating the contract

**Entry point:** A user (or a test generation run) adds a new test to the `orders_suite` test suite — say a `Missing_Pct` check on `orders.email`. The contract is currently at version 3 (saved Apr 5 09:14) and was current.

**What happens automatically:**

The staleness detector fires because a `test_definitions` row was inserted for this table group after `last_contract_save_date`. The `contract_stale` flag is set to `TRUE`.

**What the user sees next time they open the Data Contract page:**

```
┌─────────────────────────────────────────────────────────────────┐
│  ◆ orders_group  ·  Data Contract  ·  3  Apr 5 09:14  (latest)  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  ⚠ Contract may be out of date                          │    │
│  │  Since version 3 was saved (Apr 5 at 09:14):            │    │
│  │    · 1 new test added  — orders.email  Missing_Pct      │    │
│  │                                                         │    │
│  │  [Review Changes]    [Dismiss]                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│  …rest of page shows version 3 as normal…                      │
└─────────────────────────────────────────────────────────────────┘
```

User clicks **Review Changes** — a side panel opens:

```
┌──────────────────────────────────────────┐
│  Changes since version 3  (Apr 5 09:14)  │
│                                          │
│  Quality rules                           │
│    + orders.email                        │
│      Missing_Pct ≤ 5%                    │
│      origin: auto_generated              │
│      last result: ✅ passing (0.2%)      │
│                                          │
│  Schema            no changes            │
│  Governance        no changes            │
│  Suite scope       no changes            │
│                                          │
│  [Close]         [Save new version →]    │
└──────────────────────────────────────────┘
```

Clicking **Save new version →** opens the same save dialog as Flow C — showing pending changes with a label field — before committing:

```
┌────────────────────────────────────────┐
│  Save as Version 4                     │
│  (current latest: version 3)           │
│                                        │
│  Changes to include:                   │
│    + orders.email  Missing_Pct ≤ 5%    │
│                                        │
│  Label (optional):                     │
│  [________________________________]    │
│                                        │
│  [Cancel]          [Save Version 4]    │
└────────────────────────────────────────┘
```

The panel shows what specifically changed along with the new test's current result so the user can see it's already passing before committing.

The user has two choices:

**Option 1 — Save as version 4.** Clicking "Save new version →" in the diff panel opens the label dialog and confirms. The staleness banner clears.

**Option 2 — Dismiss.** The banner is hidden for this session. The test still exists and runs, but version 3 remains the saved contract. The stale indicator reappears on next load until the user decides to save.

There is no way to "reject" a test from within the contract page — if the test shouldn't exist, it needs to be removed from the test suite first. Once removed, the staleness detector fires again showing a deletion, and saving would produce a version that matches reality.

---

## 13. Tests

Tests follow the existing convention: `pytest -m unit` for fast no-DB tests, `pytest -m integration` for tests that require a live database. All new test files live under `tests/unit/` or `tests/integration/` mirroring the module they test.

---

### Existing tests that need updating

**`tests/unit/commands/test_data_contract_export.py`**
- `Test_ValidStatuses` — references `{"proposed", "draft", "active", "deprecated", "retired"}` from the old lifecycle model. The `status` field is no longer used; remove or update this class.
- `Test_RunExportDataContract` — the export function is now a **preview generator**, not a page renderer. Tests that assert on `contract_status` in the YAML output should be removed or redirected to snapshot tests.

**`tests/unit/ui/test_data_contract_page.py`**
- Add tests for the first-time flow state (no saved version → prerequisites shown).
- Add tests for the dirty-button state (pending edits → save button active).
- Add tests for the historic version read-only state.

---

### New test files

#### `tests/unit/commands/test_contract_versions.py`

Version management logic — no DB required, all logic tested via mocked DB calls.

```
Test_VersionAutoIncrement
  test_first_save_produces_version_0
    Saving for a table group with no prior versions → version = 0
  test_second_save_produces_version_1
    Saving again → version = 1
  test_version_is_per_table_group
    Two different table groups each start at version 0 independently
  test_version_increments_by_exactly_one
    No gaps — max(existing) + 1 always

Test_FetchLatestVersion
  test_returns_highest_version_when_multiple_exist
  test_returns_none_when_no_versions_saved
  test_returns_version_0_when_only_one_version_exists

Test_FetchVersionByNumber
  test_returns_correct_version_for_valid_number
  test_returns_none_for_nonexistent_version_number
  test_returns_none_for_wrong_table_group_id

Test_FetchVersionHistory
  test_returns_all_versions_ordered_newest_first
  test_returns_empty_list_when_no_versions
  test_each_entry_has_version_saved_at_and_label

Test_SaveContractVersion
  test_persists_yaml_string_verbatim
  test_saves_correct_table_group_id
  test_saves_current_timestamp_as_saved_at
  test_label_is_optional_and_nullable
  test_raises_when_table_group_id_not_found
```

---

#### `tests/unit/commands/test_staleness_detection.py`

Staleness flag logic — all pure function tests, no DB.

```
Test_StalenessSignals
  test_profiling_run_after_save_date_marks_stale
    profiling_starttime > last_contract_save_date → contract_stale = TRUE
  test_profiling_run_before_save_date_does_not_mark_stale
    profiling_starttime ≤ last_contract_save_date → no change
  test_test_definition_insert_marks_stale
  test_test_definition_update_marks_stale
  test_test_definition_delete_marks_stale
  test_suite_include_in_contract_toggle_marks_stale
  test_unrelated_table_group_change_does_not_affect_staleness

Test_StalenessResetOnSave
  test_contract_stale_set_to_false_after_new_version_saved
  test_last_contract_save_date_updated_after_save
  test_stale_flag_false_when_no_version_exists
    No prior version → nothing to be stale

Test_StalenessHistoricVersions
  test_staleness_only_applies_to_latest_version
    A historic (superseded) version has no staleness concept
  test_viewing_historic_version_does_not_clear_stale_flag
```

---

#### `tests/unit/commands/test_staleness_diff.py`

Diff computation between a saved YAML snapshot and current DB state. All logic is pure; DB calls are mocked.

```
Test_SchemaDiff
  test_new_column_detected
    Column in current data_column_chars but not in snapshot → shows as added
  test_dropped_column_detected
    Column in snapshot but not in current data_column_chars → shows as dropped
  test_type_change_detected
    db_data_type differs between snapshot and current → shows as changed
  test_no_changes_returns_empty_schema_diff
  test_column_order_change_not_flagged
    Column reordering is not a meaningful schema change

Test_TestDiff
  test_new_test_detected
    test_definition in DB but not in snapshot quality section → shows as added
  test_removed_test_detected
    Rule ID in snapshot but test_active = 'N' or deleted in DB → shows as removed
  test_threshold_change_detected
    threshold_value differs between snapshot rule and current test_definition
  test_tolerance_band_change_detected
    lower_tolerance or upper_tolerance changed
  test_description_change_detected
  test_no_changes_returns_empty_test_diff
  test_inactive_tests_not_in_snapshot_not_flagged_as_new
    Export only includes active tests; inactive tests should not appear as additions

Test_SuiteScopeDiff
  test_suite_added_to_contract_detected
    New suite with include_in_contract = TRUE that was not in snapshot x-testgen.includedSuites
  test_suite_removed_from_contract_detected
    Suite in snapshot includedSuites now has include_in_contract = FALSE
  test_no_scope_changes_returns_empty_diff
  test_monitor_suite_changes_ignored
    is_monitor = TRUE suites are always excluded; toggling them is not a scope change

Test_DiffSummary
  test_summary_empty_when_no_changes
  test_summary_lists_all_change_categories
  test_each_diff_entry_has_category_field_name_and_change_type
    change_type: "added" | "removed" | "changed"
```

---

#### `tests/unit/ui/test_contract_pending_edits.py`

Pending edit accumulation and persistence model — unit tests against the session-state logic, no Streamlit runtime required.

```
Test_PendingEditAccumulation
  test_governance_edit_added_to_pending_set
    Applying a governance dialog edit adds it to the in-memory pending list
  test_second_edit_to_same_field_replaces_first
    Editing customer_id classification twice keeps only the latest value
  test_test_threshold_edit_added_to_pending_set
  test_pending_edits_from_different_columns_accumulate_independently
  test_pending_count_reflects_number_of_distinct_changes

Test_PendingEditNotInDB
  test_governance_edit_not_written_to_data_column_chars_until_save
    data_column_chars is not touched while edit is pending
  test_test_edit_not_written_to_test_definitions_until_save

Test_PendingEditAtomicWrite
  test_all_pending_edits_written_on_version_save
    Governance edits → data_column_chars, test edits → test_definitions, both in same transaction
  test_snapshot_taken_after_db_writes
    The YAML snapshot reflects the written values, not the pre-edit state
  test_version_number_increments_after_successful_save
  test_no_db_write_on_cancel
    Clicking Cancel in the save dialog discards pending edits with no DB side-effects

Test_PendingEditDiscard
  test_navigating_away_discards_pending_edits
    Session state cleared on navigation; DB unchanged
  test_discard_does_not_affect_already_saved_versions

Test_DirtyButtonState
  test_save_button_inactive_when_no_pending_edits
  test_save_button_active_when_at_least_one_pending_edit
  test_save_button_tooltip_lists_pending_change_count
  test_button_returns_to_inactive_after_successful_save
  test_button_returns_to_inactive_after_discard
```

---

#### `tests/unit/ui/test_contract_first_time_flow.py`

Prerequisites check and first-time generation — no DB, mocked data.

```
Test_PrerequisitesCheck
  test_generate_button_enabled_when_profiling_and_suite_exist
  test_generate_button_disabled_when_no_profiling_run
  test_generate_button_disabled_when_no_test_suites
  test_generate_button_disabled_when_both_missing
  test_metadata_warning_shown_when_coverage_below_threshold
    < 25% of columns have descriptions/PII flags → show advisory
  test_metadata_warning_not_shown_when_coverage_sufficient
  test_profiling_link_shown_when_profiling_missing
  test_suite_link_shown_when_suites_missing

Test_PreviewGeneration
  test_preview_shows_coverage_percentage
  test_preview_shows_test_count
  test_preview_shows_gap_analysis_errors
  test_preview_shows_gap_analysis_warnings
  test_preview_gaps_do_not_block_save
  test_save_stores_version_0

Test_FirstTimeSaveTransition
  test_page_shows_normal_view_after_first_save
  test_health_cards_visible_after_save
  test_no_stale_banner_immediately_after_save
```

---

#### `tests/unit/ui/test_contract_historic_view.py`

Viewing a past version — tests against the rendering logic, no Streamlit runtime.

```
Test_HistoricVersionBanner
  test_blue_banner_shown_when_version_is_not_latest
  test_banner_shows_version_number_and_save_timestamp
  test_banner_shows_optional_label_when_present
  test_no_banner_when_viewing_latest_version
  test_view_latest_link_present_in_banner

Test_HistoricVersionReadOnly
  test_save_button_hidden_on_historic_version
  test_refresh_button_disabled_on_historic_version
  test_claim_chip_click_shows_readonly_dialog_not_edit
  test_edit_tooltip_instructs_user_to_switch_to_latest

Test_HistoricVersionCoverageConsistency
  test_coverage_pct_is_deterministic_from_snapshot
    Same snapshot always produces same coverage % regardless of when rendered
  test_coverage_not_affected_by_new_columns_added_after_snapshot

Test_HistoricVersionLiveOverlay
  test_test_health_card_shows_live_results_on_old_rule_set
    Rules from old snapshot are matched against current test_results by ID
  test_rule_id_not_in_current_db_shows_as_not_run
    A test deleted after the snapshot was saved shows "not run" not an error
  test_hygiene_card_shows_current_anomalies_with_disclaimer
    Anomaly count is always live; banner/caption notes this explicitly
```

---

#### `tests/unit/ui/test_contract_staleness_ui.py`

Staleness banner rendering and interactions.

```
Test_StalenessBanner
  test_banner_shown_when_contract_stale_is_true
  test_banner_hidden_when_contract_stale_is_false
  test_banner_shows_specific_change_categories
    "1 new test", "2 new columns" — not a generic "something changed"
  test_banner_dismissed_per_session
    Dismiss hides banner; next page load re-shows it

Test_ReviewChangesPanel
  test_panel_shows_added_tests_with_current_result
  test_panel_shows_dropped_columns
  test_panel_shows_type_changes
  test_panel_shows_no_changes_sections_as_clean
  test_save_from_panel_opens_save_dialog
  test_close_from_panel_returns_to_normal_view

Test_SaveFromStaleness
  test_save_from_banner_opens_same_save_dialog_as_dirty_button
    Consistent — both go through the review-and-label dialog
  test_save_increments_version_by_one
  test_stale_flag_cleared_after_save
```

---

### Test coverage targets

| Area | Files | Priority |
|---|---|---|
| Version auto-increment and fetch | `test_contract_versions.py` | Near-term — blocks all save flows |
| Staleness flag signals | `test_staleness_detection.py` | Near-term — core of the new model |
| Staleness diff computation | `test_staleness_diff.py` | Near-term — needed for Review Changes panel |
| Pending edit accumulation and atomic write | `test_contract_pending_edits.py` | Near-term — blocks Flow C |
| First-time flow prerequisites | `test_contract_first_time_flow.py` | Near-term — blocks Flow A |
| Historic view rendering and read-only | `test_contract_historic_view.py` | Medium-term — depends on version picker |
| Staleness banner and panel interactions | `test_contract_staleness_ui.py` | Medium-term — depends on diff panel |

---

## 14. Planned Work

### Implemented ✅

| Item | Status |
|---|---|
| `data_contracts` table (`0184_incremental_upgrade.sql`) | ✅ Done — `version` integer, `saved_at`, `label`, `contract_yaml`, `UNIQUE(table_group_id, version)` |
| `contract_stale` + `last_contract_save_date` on `table_groups` | ✅ Done — `0184_incremental_upgrade.sql` |
| Save / version flow — atomic `INSERT … SELECT MAX+1 … RETURNING version` | ✅ Done — `contract_versions.py` |
| "Save new version" button — always visible on latest, dirty indicator when pending edits | ✅ Done — `data_contract.py` render() |
| Staleness detection — profiling run hook in `run_profiling.py` | ✅ Done — calls `mark_contract_stale` after successful run |
| Staleness diff computation — `StaleDiff` dataclass (schema / quality / governance / suite scope) | ✅ Done — `contract_staleness.py` |
| Staleness banner + Review Changes diff panel | ✅ Done — `_render_staleness_banner`, `_review_changes_panel` |
| First-time generation wizard — prerequisites → preview → save as version 0 | ✅ Done — `_render_first_time_flow` |
| Version history dropdown — version picker in header row, right-aligned Save button | ✅ Done — `data_contract.py` render() |
| Pending edit model — `dc_yaml` / `dc_pending` co-ownership, YAML patch-on-edit | ✅ Done — `_apply_pending_governance_edit`, `_apply_pending_test_edit`, `_patch_yaml_governance` |
| 93 contract-specific unit tests (versioning + staleness + pending edits) | ✅ Done |
| Navigation from Project Dashboard, Table Group list, and Test Suites | ✅ Done |

### Backlog

| Priority | Item |
|---|---|
| Medium | Confirm-on-navigate-away — warn the user when they have pending edits and click away from the page |
| Medium | Column_Schema_Assert — per-column DDL assertion test complementing Schema_Drift |
| Low | Version diff view — side-by-side comparison between any two saved versions |
| Low | Staleness notification — email alert when a saved contract becomes stale |
| Low | External catalog publish — push saved YAML to Atlan, DataHub, or OpenMetadata on new version save |
| Low | ODPS v4.1 adapter — wrap ODCS output inside OpenDataProduct for catalog publishing |
| Low | Consumer registry — track who relies on a contract; notify on new version |
| Low | Multi-table-group contracts — one contract spanning multiple table groups |
