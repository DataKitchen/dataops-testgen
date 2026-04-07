# Coverage Matrix Redesign — Design Spec

**Date:** 2026-04-07  
**Branch:** data-contracts-vibe  
**Scope:** Two surfaces — (1) the Contract Completeness health card on the main data contract page, and (2) the Coverage Matrix tab.

---

## Background

The current coverage model is binary: a column is either "covered" (has any non-schema term) or not. This collapses three meaningfully different enforcement levels into one number, hiding the difference between a database constraint, an active test, and a manually declared description. The redesign introduces a three-bucket enforcement model surfaced across both the health card and the coverage matrix tab.

---

## Enforcement Tiers

Each column or table-level element is assigned to exactly one tier — its highest enforcement level. Highest wins.

| Tier | Definition | Verif types |
|------|-----------|-------------|
| **TestGen Enforced** | Has at least one active test or monitor | `tested`, `monitored` |
| **DB Enforced only** | Has a meaningful DDL constraint beyond bare type (NOT NULL, PK, FK, length/precision); no tests or monitors | `db_enforced` beyond bare data type |
| **Unenforced only** | Has observed or declared terms; no tests, monitors, or meaningful DDL constraints | `observed`, `declared` |
| **Uncovered** | Has nothing beyond a bare data type | — |

**Tier assignment logic (Python, `_is_covered` replacement):**

```python
def _classify_tier(prop: dict, col_rules: list[dict]) -> str:
    """Assign the highest enforcement tier to a column/element."""
    if col_rules:
        return "tg"           # any test or monitor
    if _has_meaningful_ddl(prop):
        return "db"           # NOT NULL, PK, FK, length/precision constraint
    if _has_unenforced_terms(prop):
        return "unf"          # observed stats or declared metadata
    return "none"             # bare data type only
```

Where `_has_meaningful_ddl` = NOT NULL, PK, FK, char-constrained types (VARCHAR(n)), numeric precision, or integer types. Bare `TEXT`, `JSONB`, `TIMESTAMP` without constraints = not meaningful DDL.  
Where `_has_unenforced_terms` = any of: `classification`, `criticalDataElement`, `description`, `format`, min/max observations.

**N (denominator):** Columns + table-level elements. Each table contributes one `(table-level)` row to N.

---

## Surface 1: Contract Completeness Health Card

**Location:** `HealthGrid` in `data_contract.js` — the existing "Contract Completeness" card (currently shows `coverage_pct%` + single progress bar).

### Redesign

Replace the single percentage + bar with four stacked progress bars, one per tier. The card remains clickable (navigates to the matrix tab).

**Visual spec:**

```
┌─────────────────────────────────────────────────────┐
│ ✓ Contract Completeness              [↗ open_in_new] │
│                                                      │
│ ⚡ TestGen Enforced  ████████░░░░░░░░░░░░  9 / 23   │
│ 🏛 DB Enforced only  ████░░░░░░░░░░░░░░░░  4 / 23   │
│ 📋 Unenforced only   ████░░░░░░░░░░░░░░░░  4 / 23   │
│ ○  Uncovered         ██████░░░░░░░░░░░░░░  6 / 23   │
└─────────────────────────────────────────────────────┘
```

- Each bar shares the same scale (N = total elements).
- Bar colors: TestGen = `#22c55e`, DB = `#818cf8`, Unenforced = `#f59e0b`, Uncovered = `#4b5563`.
- Label width: fixed at ~160px so all bars align.
- Count: right-aligned `X / N` in the bar's color.
- No sub-caption text ("X of N columns have ≥1 non-schema term" is removed).
- The existing "View N uncovered →" filter button is removed from this card (that filter lives on the matrix tab now).
- Clicking the card still navigates to the matrix tab (`activeTab.val = 'matrix'`).

**Backend: new health fields required.**  
`_render_health_dashboard` / `_quality_counts` must compute and pass:

```python
{
    "tg_enforced":  int,   # elements with tier == "tg"
    "db_enforced":  int,   # elements with tier == "db"
    "unenforced":   int,   # elements with tier == "unf"
    "uncovered":    int,   # elements with tier == "none"
    "n_elements":   int,   # total columns + table-level rows
}
```

These replace `coverage_pct`, `covered`, and `n_cols` in the health dict (or add alongside for backwards compat during transition).

---

## Surface 2: Coverage Matrix Tab

**Location:** `CoverageMatrix(matrix, suiteScope, tables)` in `data_contract.js`, rendered when `activeTab.val === 'matrix'`.

### Layout

```
[Contract Completeness bars — always expanded]

Coverage by table

[orders accordion ▶ | ⚡5 · 🏛0 · 📋1 · ○1  ]    ← closed
[customers accordion ▼ ]                             ← open
  ┌─────────────────────────────────────────────────┐
  │ Column / Table │ ⚡ TestGen   │ 🏛 DB │ 📋 Unf │ Uncov │
  │                │ Tests│Monit  │ DDL  │ Obs│Decl│       │
  ├────────────────┼──────┼───────┼──────┼───┼────┼───────┤
  │ (table-level)  │      │📡 Vol │  ·   │ · │  · │       │
  │ customer_id PK │✅Uniq│  ·    │BIGINT│ · │  · │       │
  │ email          │  ·   │  ·    │VARCH │📸 │🏷  │       │
  │ created_at     │  ·   │  ·    │TIMES │ · │  · │  Yes  │
  └─────────────────────────────────────────────────┘
[products accordion ▶ | ⚡2 · 🏛2 · 📋1 · ○2  ]
```

### Contract Completeness section (top of matrix tab)

- Identical four-bar layout as the health card above, but rendered inline at the top of the matrix tab — not in an accordion, always visible.
- Subtitle line: `"{n_elements} elements · each assigned to its highest enforcement tier"`.
- Each bar row is **clickable as a cross-filter**: clicking a row filters all table accordions below to show only rows matching that tier. Non-selected rows dim to 30% opacity. Clicking again clears the filter.
- This replaces the existing filter pills/buttons currently in `HealthGrid`.

### Per-table accordions

Each table in the matrix renders as a collapsible accordion.

**Closed state:**
- Shows table name (monospace) + element count badge.
- Shows four compact pills scoped to that table's counts: `⚡ N · 🏛 N · 📋 N · ○ N`.
- Pills are display-only (not clickable in closed state).

**Open state:**
- Pills are hidden (`visibility: hidden`, not removed, to preserve header height).
- Shows the matrix table.

### Matrix table columns (in this order)

| # | Group header | Sub-columns | CSS class |
|---|-------------|-------------|-----------|
| 1 | Column / Table | _(name cell)_ | `col-name` |
| 2 | ⚡ TestGen Enforced | Tests, Monitors | `tg-cell` |
| 3 | 🏛 DB Enforced | DDL | `db-cell` |
| 4 | 📋 Unenforced | Observed, Declared | `unf-cell` |
| 5 | Uncovered | _(flag cell)_ | `unc-cell` |

Column ordering is intentional: most valuable enforcement left, flag right.

### Column name cell

- Colored dot (6px circle) as coverage tier indicator:
  - TestGen enforced: `#22c55e` (green)
  - DB enforced only: `#818cf8` (purple)
  - Unenforced only: `#f59e0b` (amber)
  - Uncovered: `#374151` with border (dark gray)
- Table-level row: italic, slightly lighter text, `padding-left: 16px`.
- Column rows: monospace font, `padding-left: 20px`.
- PK badge shown inline where applicable.

### Uncovered flag cell

- Shows a red `Yes` pill (`background: rgba(239,68,68,0.18)`, `color: #f87171`, `border: 1px solid rgba(239,68,68,0.35)`) **only** when the element has no terms in any of the three active buckets (tier == "none").
- Empty (`·`) for all other tiers.
- Column header: "Uncovered", right-aligned group header `color: #ef4444`.

### Totals row

Each table section ends with a totals row showing aggregate chip counts per sub-column: `N tests · N monitors · N DDL · N obs · N decl`. Uncovered cell is blank.

### Cross-filter interaction

- Clicking a bar row in the completeness section at top sets `activeFilter` to that tier.
- All `data-row` elements with a non-matching `data-tier` attribute are hidden.
- Table accordions that become fully empty (all rows hidden) collapse their body but remain visible in the list.
- Filter clears on second click of the same bar, or on tab change.

---

## Backend Changes

### `data_contract_props.py`

1. **Add `_classify_tier(prop, col_rules) -> str`** — replaces `_is_covered`. Returns `"tg" | "db" | "unf" | "none"`.
2. **Add `_has_meaningful_ddl(prop) -> bool`** — NOT NULL, PK, FK, char-constrained/numeric-precision types. Bare TEXT/JSONB/TIMESTAMP/etc. without constraints = False.
3. **Update `_build_contract_props`** — populate `col["tier"]` on each column dict instead of `col["covered"]`.
4. **Update health stats** — compute `tg_enforced`, `db_enforced`, `unenforced`, `uncovered`, `n_elements` and include in the returned `health` dict. Remove `coverage_pct`, `covered`, `n_cols`.
5. **Update `_column_coverage_tiers`** if used elsewhere to use tier classification.

### `data_contract.py`

1. **`_render_health_dashboard`** — remove binary coverage block; pass new tier counts through to JS health dict.
2. Remove `_is_covered` import and usages.

### `data_contract.js`

1. **`HealthGrid` coverage card** — replace single bar with four stacked bars using `health.tg_enforced`, `health.db_enforced`, `health.unenforced`, `health.uncovered`, `health.n_elements`.
2. **`CoverageMatrix`** — add completeness bars at top; restructure matrix columns to the new order; add `Uncovered` flag column; add per-table accordion collapse/expand with pill summary.
3. **`COVERED_VERIFS`** — remove or update; tier classification now lives in Python and is passed as `col.tier`.
4. **Filter state** — the `"uncovered"` filter string now represents tier `"none"`. Update `colFilter` to use `col.tier` instead of checking `COVERED_VERIFS`.

---

## Out of Scope

- No changes to the Terms Detail tab, YAML tab, Gap Analysis, or import/export flows.
- No changes to the test health card or anomaly card in `HealthGrid`.
- No new DB migrations — tier classification is computed at render time from existing data.

---

## Mockup Reference

Browser mockups saved to `.superpowers/brainstorm/5496-1775593035/content/`:
- `coverage-matrix-v1.html` — initial three-bucket matrix exploration
- `coverage-completeness-v1.html` — variants A/B/C for completeness bars
- `coverage-full-page-v1.html` through `v4.html` — full-page iterations; **v4 is the approved design**
