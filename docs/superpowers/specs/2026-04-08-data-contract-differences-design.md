# Data Contract Differences — Design Spec
**Date:** 2026-04-08
**Branch:** data-contracts-vibe

---

## Overview

Add a **Contract Term Differences tab** to the Data Contract page and replace the existing **Test Health** and **Hygiene** top cards with two new cards that surface contract drift and compliance at a glance.

The core idea: compare the saved contract version (YAML snapshot) against the current live TestGen state, classify every quality term by its drift status (same / changed / new / deleted), and show enforcement-tier compliance for the terms TestGen actively runs.

---

## Scope

### What changes
1. `testgen/commands/contract_staleness.py` — new `TermStatus`, `TermDiffEntry`, `TermDiffResult` data structures and `compute_term_diff()` function
2. `testgen/ui/views/data_contract.py` — replace `_render_health_dashboard()` cards 2 & 3; add Contract Term Differences tab to page render
3. `testgen/ui/views/data_contract_props.py` — no change (existing `_classify_enforcement_tier` tiers reused)

### What does not change
- Coverage card content — unchanged; label is renamed (see Card 1 below)
- Existing `StaleDiff` / `compute_staleness_diff` — kept for the staleness banner
- Version picker, save/regenerate toolbar, unsaved changes banner

---

## Data Model

### Term statuses
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

### Data structures
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

---

## Card 1 — Contract Term Coverage (replaces Coverage)

Card label is dynamic: **"Version {N} Contract Term Coverage"** (e.g. "Version 12 Contract Term Coverage").
Content is unchanged from the current Coverage card.
The existing "Contract Claim Completeness" tab is renamed to **"Contract Term Coverage"**.

---

## Card 2 — Contract Diff Summary (replaces Test Health)

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

---

## Card 3 — Compliance Breakdown (replaces Hygiene)

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
- **Scope:** only contract terms (rule IDs in the saved YAML) are counted — TestGen tests outside the contract are excluded
- Counts pulled from `_fetch_test_statuses()` and `_fetch_anomalies()` (already fetched on page load)

---

## Differences Tab

A new tab added to the contract page tab bar, between the existing tabs and the YAML view.

### Layout — four accordions, top to bottom

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

### Accordion behavior
- Accordion header shows count: e.g. `Changed (8)`
- Same accordion starts collapsed; all others start expanded if they have entries
- If a category has 0 entries, the accordion is hidden entirely

### Filtering from top cards
Clicking a status chip on Card 2 (same / changed / deleted / new) deep-links to the Contract Term Differences tab with that accordion pre-expanded and others collapsed.

---

## Empty / edge states

| Condition | Behavior |
|---|---|
| No saved version | Cards 2 & 3 show "No contract saved yet" placeholder |
| All terms same | Contract Term Differences tab shows only the Same accordion, expanded |
| No TestGen tests | `tg_count = 0`; Card 3 shows database enforced + unenforced only |
| Viewing a historic version | Cards 2 & 3 still compute diff against that version vs. current TestGen; read-only banner remains |

---

## Contract Term Compliance Tab

A fifth tab — **Contract Term Compliance** — provides term-by-term drill-down of Card 3.

**Scope note:** Only the N contract terms whose IDs appear in the saved YAML are evaluated. TestGen tests outside the contract are excluded entirely.

**Three accordions** (all expanded by default if non-empty):

### Monitors
Each row: `element` · `test_type` · status chip
Statuses: `Passed` · `Failed` · `Warning` · `Error` · `Not Run`

### Tests
Each row: `element` · `test_type` · status chip
Statuses: `Passed` · `Failed` · `Warning` · `Error` · `Not Run`

### Hygiene
Each row: `element` · `anomaly_type` · likelihood chip
Statuses: `Definite` · `Likely` · `Possible`

Accordion headers show aggregate status counts, e.g.:
```
Tests    24 passed  1 warning  1 failed  2 not run
Hygiene  2 definite  3 likely  4 possible
```

---

## Files Changed

| File | Change |
|---|---|
| `testgen/commands/contract_staleness.py` | Add `TermStatus`, `TermDiffEntry`, `TermDiffResult`, `compute_term_diff()` |
| `testgen/ui/views/data_contract.py` | Replace cards 1 label, 2 & 3 in `_render_health_dashboard()`; add Contract Term Differences and Contract Term Compliance tabs |
| `testgen/ui/components/frontend/js/pages/data_contract.js` | Rename "Contract Claim Completeness" tab to "Contract Term Coverage"; add "Contract Term Differences" and "Contract Term Compliance" tabs and their rendered content |

No new files. No DB schema changes.
