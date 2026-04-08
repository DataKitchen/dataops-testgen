# Contract Term Differences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Contract Term Differences" and "Contract Term Compliance" tabs and top cards to the Data Contract page, surfacing per-term drift status and enforcement compliance against the saved YAML snapshot.

**Architecture:** New `compute_term_diff()` in `contract_staleness.py` computes a diff and compliance counts using one SQL query (includes monitors). Python serializes the result into `props["term_diff"]`. VanJS `HealthGrid` gains two new cards; two new tab components render the accordion detail views.

**Tech Stack:** Python 3.12 dataclasses, SQLAlchemy raw SQL via `fetch_dict_from_db`, VanJS, inline CSS in the existing `stylesheet` template literal.

---

## File Map

| File | Change |
|------|--------|
| `testgen/commands/contract_staleness.py` | Add `TermStatus`, `TermDiffEntry`, `TermDiffResult`, `_add_status_count()`, `compute_term_diff()` |
| `tests/unit/commands/test_contract_staleness.py` | Add `Test_ComputeTermDiff` class |
| `testgen/ui/views/data_contract.py` | Import new symbols; call `compute_term_diff`; add `props["term_diff"]` |
| `testgen/ui/components/frontend/js/pages/data_contract.js` | Rename Coverage label in `HealthGrid` + `TABS`; replace Test Health card; replace Hygiene card; add `DifferencesTab`; add `ComplianceTab`; add `diffFilter` state; update tab switcher and `TABS`; add CSS |

---

### Task 1: Add `TermDiffEntry`, `TermDiffResult`, and `compute_term_diff()` to `contract_staleness.py`

**Files:**
- Modify: `testgen/commands/contract_staleness.py`
- Test: `tests/unit/commands/test_contract_staleness.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/commands/test_contract_staleness.py` — import the new symbols and add helpers and the test class:

```python
from testgen.commands.contract_staleness import (
    StaleDiff, compute_staleness_diff,
    TermDiffEntry, TermDiffResult, compute_term_diff,
)
```

Add these helpers right after the existing `_suite_row` helper:

```python
def _term_test_row(
    test_id: str,
    threshold: str = "100",
    is_monitor: bool = False,
    last_status: str | None = None,
    table: str = "orders",
    column: str = "amount",
) -> dict:
    return {
        "id": test_id,
        "test_type": "Row_Ct",
        "table_name": table,
        "column_name": column,
        "threshold_value": threshold,
        "is_monitor": is_monitor,
        "last_status": last_status,  # already normalized (passed/failed/…/not_run)
    }


def _diff_patch_db(test_rows: list | None = None) -> list:
    """Return side_effect list for the single fetch_dict_from_db call in compute_term_diff."""
    return [test_rows if test_rows is not None else []]
```

Add the full test class:

```python
class Test_ComputeTermDiff:
    def test_same_when_threshold_matches(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1000}])
        rows = [_term_test_row(test_id, threshold="1000")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        same = [e for e in result.entries if e.status == "same"]
        assert len(same) == 1
        assert same[0].test_type == "Row_Ct"
        assert same[0].detail is None

    def test_changed_when_threshold_differs(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 500}])
        rows = [_term_test_row(test_id, threshold="1000")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        changed = [e for e in result.entries if e.status == "changed"]
        assert len(changed) == 1
        assert "500" in changed[0].detail
        assert "1000" in changed[0].detail

    def test_deleted_when_not_in_testgen(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeLessOrEqualTo": 0}])
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db([])):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        deleted = [e for e in result.entries if e.status == "deleted"]
        assert len(deleted) == 1
        assert deleted[0].element == "orders.amount"

    def test_new_when_not_in_saved_yaml(self):
        new_id = str(uuid4())
        saved = _yaml_with_quality([])
        rows = [_term_test_row(new_id, threshold="100")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        new = [e for e in result.entries if e.status == "new"]
        assert len(new) == 1

    def test_saved_and_current_counts(self):
        id1, id2 = str(uuid4()), str(uuid4())
        saved = _yaml_with_quality([{"id": id1, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 100}])
        rows = [
            _term_test_row(id1, threshold="100"),
            _term_test_row(id2, threshold="200"),
        ]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.saved_count == 1
        assert result.current_count == 2

    def test_monitor_status_counted_separately(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", is_monitor=True, last_status="passed")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.tg_monitor_passed == 1
        assert result.tg_test_passed == 0

    def test_test_status_counted_separately(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", is_monitor=False, last_status="failed")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.tg_test_failed == 1
        assert result.tg_monitor_failed == 0

    def test_not_run_when_no_result(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", last_status=None)]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.tg_test_not_run == 1

    def test_hygiene_scoped_to_contract_elements(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", table="orders", column="amount")]
        anomalies = [
            {"table_name": "orders", "column_name": "amount", "issue_likelihood": "Definite"},
            {"table_name": "users",  "column_name": "email",  "issue_likelihood": "Likely"},   # out of contract
        ]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, anomalies)
        assert result.tg_hygiene_definite == 1
        assert result.tg_hygiene_likely == 0   # excluded because not in contract elements

    def test_invalid_yaml_returns_empty_result(self):
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db([])):
            result = compute_term_diff(TABLE_GROUP_ID, "{{invalid yaml: [}", [])
        assert result.entries == []
        assert result.saved_count == 0

    def test_entry_carries_is_monitor_flag(self):
        test_id = str(uuid4())
        saved = _yaml_with_quality([{"id": test_id, "type": "library", "element": "orders.amount",
                                     "mustBeGreaterOrEqualTo": 1}])
        rows = [_term_test_row(test_id, threshold="1", is_monitor=True, last_status="passed")]
        with patch("testgen.commands.contract_staleness.fetch_dict_from_db",
                   side_effect=_diff_patch_db(rows)):
            result = compute_term_diff(TABLE_GROUP_ID, saved, [])
        assert result.entries[0].is_monitor is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/chris.bergh/PycharmProjects/dataops-testgen
source venv/bin/activate
pytest tests/unit/commands/test_contract_staleness.py::Test_ComputeTermDiff -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'TermDiffEntry' from 'testgen.commands.contract_staleness'`

- [ ] **Step 3: Add `Literal` to the typing import in `contract_staleness.py`**

In `testgen/commands/contract_staleness.py`, change:

```python
from typing import Any
```

to:

```python
from typing import Any, Literal
```

- [ ] **Step 4: Add dataclasses and `compute_term_diff()` to `contract_staleness.py`**

After the `StaleDiff` dataclass (after line ~78 in the file, before the `# Main diff function` section), add:

```python
# ---------------------------------------------------------------------------
# Term diff data structures
# ---------------------------------------------------------------------------

TermStatus = Literal["same", "changed", "new", "deleted"]


@dataclass
class TermDiffEntry:
    element: str          # "table.column" or just "table" for table-level terms
    test_type: str
    status: TermStatus
    detail: str | None    # non-None only for "changed" rows
    last_result: str | None  # "passed"/"failed"/"warning"/"error"/"not_run"/None
    is_monitor: bool = False


@dataclass
class TermDiffResult:
    entries: list[TermDiffEntry] = field(default_factory=list)
    saved_count: int = 0
    current_count: int = 0
    # Monitor statuses (contract-scoped)
    tg_monitor_passed: int = 0
    tg_monitor_failed: int = 0
    tg_monitor_warning: int = 0
    tg_monitor_error: int = 0
    tg_monitor_not_run: int = 0
    # Test statuses (contract-scoped)
    tg_test_passed: int = 0
    tg_test_failed: int = 0
    tg_test_warning: int = 0
    tg_test_error: int = 0
    tg_test_not_run: int = 0
    # Hygiene counts (contract-scoped anomalies)
    tg_hygiene_definite: int = 0
    tg_hygiene_likely: int = 0
    tg_hygiene_possible: int = 0
```

After the `StaleDiff` section and before `compute_staleness_diff`, add the helper and the new function:

```python
def _add_status_count(result: TermDiffResult, is_monitor: bool, last_status: str | None) -> None:
    """Increment the appropriate status counter on *result*."""
    s = last_status if last_status in ("passed", "failed", "warning", "error") else "not_run"
    prefix = "tg_monitor" if is_monitor else "tg_test"
    attr = f"{prefix}_{s}"
    setattr(result, attr, getattr(result, attr) + 1)


@with_database_session
def compute_term_diff(
    table_group_id: str,
    saved_yaml: str,
    anomalies: list[dict[str, Any]],
) -> TermDiffResult:
    """
    Compare the saved contract YAML snapshot against the current active test definitions
    (including monitors) and return a TermDiffResult with per-term diff entries and
    compliance status counts.

    Key rule: terms absent from the saved YAML are surfaced as "new" (they exist in
    TestGen but were never in the contract). Terms in the saved YAML but gone from
    TestGen are "deleted". Hygiene counts are scoped to elements mentioned in the
    saved YAML's quality rules.
    """
    result = TermDiffResult()
    schema = get_tg_schema()

    # ------------------------------------------------------------------
    # 1. Parse the saved YAML
    # ------------------------------------------------------------------
    try:
        snapshot: dict[str, Any] = yaml.safe_load(saved_yaml) or {}
    except yaml.YAMLError as exc:
        LOG.warning("compute_term_diff: failed to parse saved YAML: %s", exc)
        return result
    if not isinstance(snapshot, dict):
        return result

    saved_quality: dict[str, dict[str, Any]] = {}
    for rule in snapshot.get("quality") or []:
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get("id")
        if rule_id:
            saved_quality[str(rule_id)] = rule

    result.saved_count = len(saved_quality)

    # ------------------------------------------------------------------
    # 2. Query current test definitions (monitors included)
    # ------------------------------------------------------------------
    test_rows = fetch_dict_from_db(
        f"""
        SELECT td.id::text AS id,
               td.test_type,
               td.table_name,
               td.column_name,
               td.threshold_value,
               COALESCE(ts.is_monitor, FALSE) AS is_monitor,
               CASE tr.result_status
                   WHEN 'Passed'  THEN 'passed'
                   WHEN 'Failed'  THEN 'failed'
                   WHEN 'Warning' THEN 'warning'
                   WHEN 'Error'   THEN 'error'
                   ELSE NULL
               END AS last_status
        FROM {schema}.test_definitions td
        JOIN {schema}.test_suites ts ON ts.id = td.test_suite_id
        LEFT JOIN LATERAL (
            SELECT result_status FROM {schema}.test_results
            WHERE  test_definition_id = td.id
            ORDER  BY test_time DESC LIMIT 1
        ) tr ON TRUE
        WHERE ts.table_groups_id         = :tg_id
          AND ts.include_in_contract     IS NOT FALSE
          AND td.test_active             = 'Y'
        """,
        params={"tg_id": table_group_id},
    )
    current_tests: dict[str, dict[str, Any]] = {str(r["id"]): dict(r) for r in test_rows}
    result.current_count = len(current_tests)

    def _element_of(row: dict[str, Any]) -> str:
        col = (row.get("column_name") or "").strip()
        tbl = (row.get("table_name")  or "").strip()
        return f"{tbl}.{col}" if col else tbl

    def _snap_threshold(rule: dict[str, Any]) -> str | None:
        for op in ("mustBe", "mustBeGreaterThan", "mustBeGreaterOrEqualTo",
                   "mustBeLessThan", "mustBeLessOrEqualTo"):
            if op in rule:
                return str(rule[op])
        if "mustBeBetween" in rule:
            between = rule["mustBeBetween"]
            if isinstance(between, list) and len(between) == 2:
                return f"{between[0]},{between[1]}"
        return None

    # ------------------------------------------------------------------
    # 3. Build entries: iterate saved YAML rules
    # ------------------------------------------------------------------
    contract_elements: set[str] = set()

    for rule_id, rule in saved_quality.items():
        element = rule.get("element") or ""
        contract_elements.add(element)

        if rule_id in current_tests:
            row = current_tests[rule_id]
            is_monitor = bool(row.get("is_monitor", False))
            last_result: str | None = row.get("last_status")
            snap_thresh = _snap_threshold(rule)
            cur_thresh  = str(row.get("threshold_value") or "")

            if snap_thresh is not None and snap_thresh != cur_thresh:
                entry = TermDiffEntry(
                    element=element or _element_of(row),
                    test_type=row.get("test_type") or "",
                    status="changed",
                    detail=f"threshold: {snap_thresh} → {cur_thresh}",
                    last_result=last_result,
                    is_monitor=is_monitor,
                )
            else:
                entry = TermDiffEntry(
                    element=element or _element_of(row),
                    test_type=row.get("test_type") or "",
                    status="same",
                    detail=None,
                    last_result=last_result,
                    is_monitor=is_monitor,
                )
            result.entries.append(entry)
            _add_status_count(result, is_monitor, last_result)
        else:
            result.entries.append(TermDiffEntry(
                element=element,
                test_type="",
                status="deleted",
                detail=None,
                last_result=None,
                is_monitor=False,
            ))

    # ------------------------------------------------------------------
    # 4. New entries: in TestGen but absent from saved YAML
    # ------------------------------------------------------------------
    for test_id, row in current_tests.items():
        if test_id not in saved_quality:
            result.entries.append(TermDiffEntry(
                element=_element_of(row),
                test_type=row.get("test_type") or "",
                status="new",
                detail=None,
                last_result=row.get("last_status"),
                is_monitor=bool(row.get("is_monitor", False)),
            ))

    # ------------------------------------------------------------------
    # 5. Hygiene counts — scoped to contract elements
    # ------------------------------------------------------------------
    for anomaly in anomalies:
        tbl = (anomaly.get("table_name") or "").strip()
        col = (anomaly.get("column_name") or "").strip()
        element = f"{tbl}.{col}" if col else tbl
        if element not in contract_elements:
            continue
        likelihood = anomaly.get("issue_likelihood") or ""
        if likelihood == "Definite":
            result.tg_hygiene_definite += 1
        elif likelihood == "Likely":
            result.tg_hygiene_likely += 1
        elif likelihood == "Possible":
            result.tg_hygiene_possible += 1

    return result
```

- [ ] **Step 5: Run the tests and verify they pass**

```bash
pytest tests/unit/commands/test_contract_staleness.py::Test_ComputeTermDiff -v
```

Expected: all 11 tests PASS.

- [ ] **Step 6: Run the full staleness test suite to confirm no regressions**

```bash
pytest tests/unit/commands/test_contract_staleness.py -v
```

Expected: all existing + 11 new tests PASS.

- [ ] **Step 7: Commit**

```bash
git add testgen/commands/contract_staleness.py tests/unit/commands/test_contract_staleness.py
git commit -m "feat: add TermDiffEntry/TermDiffResult/compute_term_diff to contract_staleness"
```

---

### Task 2: Wire `compute_term_diff` into `data_contract.py` → `props["term_diff"]`

**Files:**
- Modify: `testgen/ui/views/data_contract.py`

- [ ] **Step 1: Update the import in `data_contract.py`**

Find the existing import line:

```python
from testgen.commands.contract_staleness import StaleDiff, compute_staleness_diff
```

Replace it with:

```python
from testgen.commands.contract_staleness import (
    StaleDiff,
    TermDiffResult,
    compute_staleness_diff,
    compute_term_diff,
)
```

- [ ] **Step 2: Add the `compute_term_diff` call and `props["term_diff"]` assignment**

In `render()`, after the `props["version_info"] = {...}` block (around line 592) and before the `# ── Event handlers` section, add:

```python
        # ── Term diff (Card 2 / Card 3 / Differences tab / Compliance tab) ─
        term_diff: TermDiffResult = compute_term_diff(table_group_id, contract_yaml, anomalies)
        same_ct    = sum(1 for e in term_diff.entries if e.status == "same")
        changed_ct = sum(1 for e in term_diff.entries if e.status == "changed")
        deleted_ct = sum(1 for e in term_diff.entries if e.status == "deleted")
        new_ct     = sum(1 for e in term_diff.entries if e.status == "new")

        # Build per-element hygiene list scoped to contract elements
        contract_elements: set[str] = {
            e.element for e in term_diff.entries if e.element
        }
        hygiene_entries = [
            {
                "element": (
                    f"{a['table_name']}.{a['column_name']}"
                    if a.get("column_name") else a["table_name"]
                ),
                "anomaly_type":     a.get("anomaly_type", ""),
                "issue_likelihood": a.get("issue_likelihood", ""),
            }
            for a in anomalies
            if (
                f"{a['table_name']}.{a['column_name']}"
                if a.get("column_name") else a["table_name"]
            ) in contract_elements
        ]

        props["term_diff"] = {
            "saved_count":   term_diff.saved_count,
            "current_count": term_diff.current_count,
            "same_count":    same_ct,
            "changed_count": changed_ct,
            "deleted_count": deleted_ct,
            "new_count":     new_ct,
            "entries": [
                {
                    "element":     e.element,
                    "test_type":   e.test_type,
                    "status":      e.status,
                    "detail":      e.detail,
                    "last_result": e.last_result,
                    "is_monitor":  e.is_monitor,
                }
                for e in term_diff.entries
            ],
            "hygiene_entries": hygiene_entries,
            "tg_monitor_passed":  term_diff.tg_monitor_passed,
            "tg_monitor_failed":  term_diff.tg_monitor_failed,
            "tg_monitor_warning": term_diff.tg_monitor_warning,
            "tg_monitor_error":   term_diff.tg_monitor_error,
            "tg_monitor_not_run": term_diff.tg_monitor_not_run,
            "tg_test_passed":     term_diff.tg_test_passed,
            "tg_test_failed":     term_diff.tg_test_failed,
            "tg_test_warning":    term_diff.tg_test_warning,
            "tg_test_error":      term_diff.tg_test_error,
            "tg_test_not_run":    term_diff.tg_test_not_run,
            "tg_hygiene_definite": term_diff.tg_hygiene_definite,
            "tg_hygiene_likely":   term_diff.tg_hygiene_likely,
            "tg_hygiene_possible": term_diff.tg_hygiene_possible,
        }
```

- [ ] **Step 3: Verify the app starts and the page loads without errors**

```bash
source venv/bin/activate && source local.env
testgen run-app ui &
# open http://localhost:8501 — navigate to a data contract page
# check terminal for Python tracebacks
```

Expected: page loads, no `ImportError` or `TypeError` in terminal.

- [ ] **Step 4: Commit**

```bash
git add testgen/ui/views/data_contract.py
git commit -m "feat: wire compute_term_diff into data_contract props"
```

---

### Task 3: Update `HealthGrid` cards in `data_contract.js`

Rename the Coverage card label, replace the Test Health card with a Differences card, and replace the Hygiene card with a Compliance card.

**Files:**
- Modify: `testgen/ui/components/frontend/js/pages/data_contract.js`

- [ ] **Step 1: Update `HealthGrid` signature to accept new arguments**

Find the existing `HealthGrid` function definition:

```javascript
const HealthGrid = (health, activeFilter, activeTab) => {
```

Replace with:

```javascript
const HealthGrid = (health, activeFilter, activeTab, termDiff, diffFilter, versionNum) => {
```

- [ ] **Step 2: Rename the Coverage card label (label-only change, no UI content change)**

Find inside `HealthGrid`:

```javascript
            div({ class: 'health-card__label' },
                mat('verified', 13), ' Contract Claim Completeness',
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
```

Replace with:

```javascript
            div({ class: 'health-card__label' },
                mat('verified', 13), ' Contract Term Coverage',
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
```

- [ ] **Step 3: Add helper functions used by the new cards**

Add these two helpers inside `HealthGrid`, before the `return div(` at the end of the function:

```javascript
    const DiffStatusRow = (count, statusKey, label) =>
        div(
            {
                class: 'diff-status-row',
                onclick: (e) => {
                    e.stopPropagation();
                    diffFilter.val = diffFilter.val === statusKey ? '' : statusKey;
                    activeTab.val  = 'differences';
                },
            },
            span({ class: 'diff-status-count' }, count),
            span({ class: 'diff-status-label' }, label),
        );

    const StatusCount = (color, label, count) =>
        count
            ? span({ class: 'count-item' },
                   span({ class: 'count-dot', style: `background:${color}` }),
                   ` ${count} ${label}`)
            : '';

    const ComplianceCardContent = (h, td) => {
        const TierRow = (cnt, label, color) =>
            tr(
                td({ class: 'ct-count' }, cnt),
                td({ class: 'ct-label', style: `color:${color}` }, label),
            );
        const monitorTotal = td.tg_monitor_passed + td.tg_monitor_failed + td.tg_monitor_warning
                           + td.tg_monitor_error  + td.tg_monitor_not_run;
        return table(
            { class: 'compliance-tier-table' },
            tbody(
                TierRow(h.db_enforced  || 0, 'database enforced', '#818cf8'),
                TierRow(h.unenforced   || 0, 'unenforced',        '#f59e0b'),
                tr(
                    td({ class: 'ct-count' }, h.tg_enforced || 0),
                    td({ class: 'ct-label', style: 'color:#22c55e' }, 'TestGen enforced'),
                ),
                monitorTotal > 0
                    ? tr(td(), td({ class: 'ct-sub' },
                        'Monitors  ',
                        StatusCount('#22c55e', 'passed',  td.tg_monitor_passed),
                        StatusCount('#ef4444', 'failed',  td.tg_monitor_failed),
                        StatusCount('#f59e0b', 'warning', td.tg_monitor_warning),
                        StatusCount('#94a3b8', 'error',   td.tg_monitor_error),
                        StatusCount('#6b7280', 'not run', td.tg_monitor_not_run),
                      ))
                    : '',
                tr(td(), td({ class: 'ct-sub' },
                    'Tests  ',
                    StatusCount('#22c55e', 'passed',  td.tg_test_passed),
                    StatusCount('#ef4444', 'failed',  td.tg_test_failed),
                    StatusCount('#f59e0b', 'warning', td.tg_test_warning),
                    StatusCount('#94a3b8', 'error',   td.tg_test_error),
                    StatusCount('#6b7280', 'not run', td.tg_test_not_run),
                )),
                td.tg_hygiene_definite + td.tg_hygiene_likely + td.tg_hygiene_possible > 0
                    ? tr(td(), td({ class: 'ct-sub' },
                        'Hygiene  ',
                        StatusCount('#ef4444', 'definite', td.tg_hygiene_definite),
                        StatusCount('#f59e0b', 'likely',   td.tg_hygiene_likely),
                        StatusCount('#94a3b8', 'possible', td.tg_hygiene_possible),
                      ))
                    : '',
            ),
        );
    };
```

> **Note:** Inside `ComplianceCardContent` the inner `td` function (VanJS `td` element) shadows the outer `td` parameter name. Rename the outer parameter to `tdf` to avoid collision:

Correct version of `ComplianceCardContent`:

```javascript
    const ComplianceCardContent = (h, tdf) => {
        const TierRow = (cnt, label, color) =>
            tr(
                td({ class: 'ct-count' }, cnt),
                td({ class: 'ct-label', style: `color:${color}` }, label),
            );
        const monitorTotal = tdf.tg_monitor_passed + tdf.tg_monitor_failed + tdf.tg_monitor_warning
                           + tdf.tg_monitor_error  + tdf.tg_monitor_not_run;
        return table(
            { class: 'compliance-tier-table' },
            tbody(
                TierRow(h.db_enforced  || 0, 'database enforced', '#818cf8'),
                TierRow(h.unenforced   || 0, 'unenforced',        '#f59e0b'),
                tr(
                    td({ class: 'ct-count' }, h.tg_enforced || 0),
                    td({ class: 'ct-label', style: 'color:#22c55e' }, 'TestGen enforced'),
                ),
                monitorTotal > 0
                    ? tr(td(), td({ class: 'ct-sub' },
                        'Monitors  ',
                        StatusCount('#22c55e', 'passed',  tdf.tg_monitor_passed),
                        StatusCount('#ef4444', 'failed',  tdf.tg_monitor_failed),
                        StatusCount('#f59e0b', 'warning', tdf.tg_monitor_warning),
                        StatusCount('#94a3b8', 'error',   tdf.tg_monitor_error),
                        StatusCount('#6b7280', 'not run', tdf.tg_monitor_not_run),
                      ))
                    : '',
                tr(td(), td({ class: 'ct-sub' },
                    'Tests  ',
                    StatusCount('#22c55e', 'passed',  tdf.tg_test_passed),
                    StatusCount('#ef4444', 'failed',  tdf.tg_test_failed),
                    StatusCount('#f59e0b', 'warning', tdf.tg_test_warning),
                    StatusCount('#94a3b8', 'error',   tdf.tg_test_error),
                    StatusCount('#6b7280', 'not run', tdf.tg_test_not_run),
                )),
                tdf.tg_hygiene_definite + tdf.tg_hygiene_likely + tdf.tg_hygiene_possible > 0
                    ? tr(td(), td({ class: 'ct-sub' },
                        'Hygiene  ',
                        StatusCount('#ef4444', 'definite', tdf.tg_hygiene_definite),
                        StatusCount('#f59e0b', 'likely',   tdf.tg_hygiene_likely),
                        StatusCount('#94a3b8', 'possible', tdf.tg_hygiene_possible),
                      ))
                    : '',
            ),
        );
    };
```

- [ ] **Step 4: Replace the Test Health card with the Differences card**

Find the `// — Test health card` block (lines ~973–1022). Replace the **entire** card div (from `// — Test health card` through the closing `,` of that card) with:

```javascript
        // — Differences card
        div(
            {
                class: 'health-card tests health-card--link',
                onclick: () => { activeTab.val = 'differences'; },
                title: 'View Contract Term Differences',
            },
            div({ class: 'health-card__label' },
                mat('compare', 13), ` Version ${versionNum} Contract Term Differences`,
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
            termDiff
                ? [
                    div({ class: 'health-card__sub' },
                        `Saved: ${termDiff.saved_count}  ·  Current: ${termDiff.current_count}`,
                    ),
                    div(
                        { class: 'diff-rows' },
                        termDiff.same_count    ? DiffStatusRow(termDiff.same_count,    'same',    'same')    : '',
                        termDiff.changed_count ? DiffStatusRow(termDiff.changed_count, 'changed', 'changed') : '',
                        termDiff.deleted_count ? DiffStatusRow(termDiff.deleted_count, 'deleted', 'deleted') : '',
                        termDiff.new_count     ? DiffStatusRow(termDiff.new_count,     'new',     'new')     : '',
                    ),
                  ]
                : div({ class: 'health-card__sub' }, 'No saved version yet'),
        ),
```

- [ ] **Step 5: Replace the Hygiene card with the Compliance card**

Find the `// — Hygiene card` block (lines ~1023–1050). Replace the **entire** card div with:

```javascript
        // — Compliance card
        div(
            {
                class: 'health-card hygiene health-card--link',
                onclick: () => { activeTab.val = 'compliance'; },
                title: 'View Contract Term Compliance',
            },
            div({ class: 'health-card__label' },
                mat('fact_check', 13), ` Version ${versionNum} Contract Term Compliance`,
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
            termDiff
                ? ComplianceCardContent(health, termDiff)
                : div({ class: 'health-card__sub' }, 'No saved version yet'),
        ),
```

- [ ] **Step 6: Add CSS for the new card elements**

In the `stylesheet` template literal at the bottom of `data_contract.js`, add after the existing `.health-card__run-time` rule:

```css
/* ── Differences card ── */
.diff-rows { margin-top: 6px; }
.diff-status-row {
    display: flex; align-items: baseline; gap: 8px; padding: 2px 4px;
    border-radius: 4px; cursor: pointer;
}
.diff-status-row:hover { background: rgba(255,255,255,0.06); }
.diff-status-count { font-size: 15px; font-weight: 700; min-width: 28px; text-align: right; color: #e2e8f0; }
.diff-status-label { font-size: 12px; color: #94a3b8; text-transform: lowercase; }

/* ── Compliance card table ── */
.compliance-tier-table { border-collapse: collapse; width: 100%; margin-top: 4px; }
.compliance-tier-table td { padding: 1px 4px; font-size: 13px; vertical-align: top; }
.ct-count { text-align: right; font-weight: 700; color: #e2e8f0; white-space: nowrap; width: 1%; padding-right: 8px; }
.ct-label { color: #94a3b8; }
.ct-sub { color: #64748b; font-size: 11px; padding-left: 12px; padding-top: 1px; }
.ct-sub .count-item { margin-right: 6px; }
```

- [ ] **Step 7: Verify cards render in the browser**

Open the Data Contract page. The three cards should now show:
- Card 1: "Contract Term Coverage" label (content unchanged)
- Card 2: "Version N Contract Term Differences" with Saved/Current counts and status rows
- Card 3: "Version N Contract Term Compliance" with the tier table

- [ ] **Step 8: Commit**

```bash
git add testgen/ui/components/frontend/js/pages/data_contract.js
git commit -m "feat: update HealthGrid — rename coverage label, add differences and compliance cards"
```

---

### Task 4: Add `DifferencesTab` component, update `TABS`, and update tab switcher

**Files:**
- Modify: `testgen/ui/components/frontend/js/pages/data_contract.js`

- [ ] **Step 1: Rename the matrix tab label in `TABS` and add new tabs**

Find:

```javascript
const TABS = [
    { id: 'overview',  label: 'Contract Terms'   },
    { id: 'matrix',    label: 'Contract Claim Completeness' },
    { id: 'yaml',      label: 'YAML'            },
    { id: 'upload',    label: 'Upload Changes'  },
];
```

Replace with:

```javascript
const TABS = [
    { id: 'overview',    label: 'Contract Terms'            },
    { id: 'matrix',      label: 'Contract Term Coverage'    },
    { id: 'differences', label: 'Contract Term Differences' },
    { id: 'compliance',  label: 'Contract Term Compliance'  },
    { id: 'yaml',        label: 'YAML'                      },
    { id: 'upload',      label: 'Upload Changes'            },
];
```

- [ ] **Step 2: Add `DifferencesTab` component**

Add the following component just before the `// ── Main component ──` comment:

```javascript
// ── Differences tab ───────────────────────────────────────────────────────────

const DifferencesTab = (termDiff, diffFilter) => {
    if (!termDiff || termDiff.saved_count === 0) {
        return div({ class: 'dc-empty-state' }, 'No saved contract version yet.');
    }

    const entries = termDiff.entries || [];
    const grouped = {
        changed: entries.filter(e => e.status === 'changed'),
        new:     entries.filter(e => e.status === 'new'),
        deleted: entries.filter(e => e.status === 'deleted'),
        same:    entries.filter(e => e.status === 'same'),
    };

    const statusIcon = {
        changed: { glyph: '~', color: '#f59e0b' },
        new:     { glyph: '+', color: '#22c55e'  },
        deleted: { glyph: '−', color: '#ef4444'  },
        same:    { glyph: '=', color: '#6b7280'  },
    };

    const DiffRow = (entry) =>
        div(
            { class: 'diff-entry-row' },
            span(
                { style: `color:${(statusIcon[entry.status] || {}).color || '#999'};font-weight:700;margin-right:6px;min-width:14px;display:inline-block` },
                (statusIcon[entry.status] || {}).glyph || '',
            ),
            span({ class: 'diff-element' }, entry.element),
            entry.test_type ? span({ class: 'diff-test-type' }, entry.test_type) : '',
            entry.detail    ? span({ class: 'diff-detail' },    entry.detail)    : '',
        );

    const DiffAccordion = (statusKey, label, entries, defaultOpen) => {
        if (entries.length === 0) return '';
        const isOpen = van.state(
            diffFilter.val ? diffFilter.val === statusKey : defaultOpen,
        );
        return div(
            { class: 'diff-accordion' },
            div(
                {
                    class: 'diff-accordion-header',
                    onclick: () => { isOpen.val = !isOpen.val; },
                },
                () => mat(isOpen.val ? 'expand_more' : 'chevron_right', 14),
                ` ${label} (${entries.length})`,
            ),
            () => isOpen.val
                ? div({ class: 'diff-accordion-body' }, ...entries.map(DiffRow))
                : '',
        );
    };

    return div(
        { class: 'dc-differences-tab' },
        DiffAccordion('changed', 'Changed', grouped.changed, true),
        DiffAccordion('new',     'New',     grouped.new,     true),
        DiffAccordion('deleted', 'Deleted', grouped.deleted, true),
        DiffAccordion('same',    'Same',    grouped.same,    false),
    );
};
```

- [ ] **Step 3: Add `diffFilter` state to `DataContract` and pass to `HealthGrid`**

Find inside `DataContract`:

```javascript
    const activeTab = van.state('overview');
    const activeFilter = van.state('all');
```

Replace with:

```javascript
    const activeTab    = van.state('overview');
    const activeFilter = van.state('all');
    const diffFilter   = van.state('');
```

Find:

```javascript
            const tgName     = getValue(props.table_group_name) || '';
            const meta       = getValue(props.meta)         || {};
            const health     = getValue(props.health)       || {};
            const yaml       = getValue(props.yaml_content) || '';
            const tables     = getValue(props.tables)       || [];
            const matrix     = getValue(props.coverage_matrix) || [];
            const gaps       = getValue(props.gaps)         || {};
            const suiteScope = getValue(props.suite_scope)  || {};
```

Replace with:

```javascript
            const tgName     = getValue(props.table_group_name) || '';
            const meta       = getValue(props.meta)             || {};
            const health     = getValue(props.health)           || {};
            const yaml       = getValue(props.yaml_content)     || '';
            const tables     = getValue(props.tables)           || [];
            const matrix     = getValue(props.coverage_matrix)  || [];
            const gaps       = getValue(props.gaps)             || {};
            const suiteScope = getValue(props.suite_scope)      || {};
            const termDiff   = getValue(props.term_diff)        || null;
            const versionNum = (getValue(props.version_info)    || {}).version || '';
```

Find:

```javascript
                HealthGrid(health, activeFilter, activeTab),
```

Replace with:

```javascript
                HealthGrid(health, activeFilter, activeTab, termDiff, diffFilter, versionNum),
```

- [ ] **Step 4: Add `differences` case to the tab switcher**

Find the tab switcher block:

```javascript
                () => {
                    const tab = activeTab.val;
                    if (tab === 'overview') return TermsDetail(tables, activeFilter);
                    if (tab === 'matrix')   return CoverageMatrix(matrix, suiteScope, tables, health, activeTab);
                    if (tab === 'yaml')     return YamlViewer(yaml, tgName);
                    if (tab === 'upload')   return UploadTab();
                    if (tab === 'help')     return TermsHelpPanel();
                    return '';
                },
```

Replace with:

```javascript
                () => {
                    const tab = activeTab.val;
                    if (tab === 'overview')    return TermsDetail(tables, activeFilter);
                    if (tab === 'matrix')      return CoverageMatrix(matrix, suiteScope, tables, health, activeTab);
                    if (tab === 'differences') return DifferencesTab(termDiff, diffFilter);
                    if (tab === 'compliance')  return ComplianceTab(termDiff, health);
                    if (tab === 'yaml')        return YamlViewer(yaml, tgName);
                    if (tab === 'upload')      return UploadTab();
                    if (tab === 'help')        return TermsHelpPanel();
                    return '';
                },
```

> Note: `ComplianceTab` is referenced here but defined in Task 5. Do both steps before testing.

- [ ] **Step 5: Add CSS for the Differences tab**

Append to the `stylesheet` template literal:

```css
/* ── Differences tab ── */
.dc-differences-tab { padding: 16px 0; }
.dc-empty-state { padding: 32px; text-align: center; color: #64748b; font-size: 14px; }
.diff-accordion { margin-bottom: 8px; border: 1px solid #1e293b; border-radius: 6px; overflow: hidden; }
.diff-accordion-header {
    display: flex; align-items: center; gap: 6px; padding: 10px 14px;
    background: #0f172a; color: #cbd5e1; font-size: 13px; font-weight: 600;
    cursor: pointer; user-select: none;
}
.diff-accordion-header:hover { background: #1e293b; }
.diff-accordion-body { padding: 6px 0; }
.diff-entry-row {
    display: flex; align-items: baseline; gap: 10px; padding: 5px 18px;
    font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.04);
}
.diff-entry-row:last-child { border-bottom: none; }
.diff-element { font-weight: 600; color: #e2e8f0; min-width: 180px; font-family: monospace; font-size: 12px; }
.diff-test-type { color: #94a3b8; min-width: 140px; font-size: 12px; }
.diff-detail { color: #f59e0b; font-size: 11px; font-style: italic; }
```

- [ ] **Step 6: Verify the Differences tab renders**

Open the Data Contract page, click "Contract Term Differences" tab. The accordions should show the diff entries. Clicking a status row on Card 2 should jump to this tab with the relevant accordion open.

- [ ] **Step 7: Commit (partial — before Task 5 is done, do not commit yet)**

Hold the commit until after Task 5 so the `compliance` case in the tab switcher compiles.

---

### Task 5: Add `ComplianceTab` component and CSS

**Files:**
- Modify: `testgen/ui/components/frontend/js/pages/data_contract.js`

- [ ] **Step 1: Add `ComplianceTab` component**

Add immediately after the `DifferencesTab` component (before `// ── Main component ──`):

```javascript
// ── Compliance tab ────────────────────────────────────────────────────────────

const ComplianceTab = (termDiff, health) => {
    if (!termDiff || termDiff.saved_count === 0) {
        return div({ class: 'dc-empty-state' }, 'No saved contract version yet.');
    }

    const entries       = termDiff.entries || [];
    const activeEntries = entries.filter(e => e.status === 'same' || e.status === 'changed');
    const monitorRows   = activeEntries.filter(e => e.is_monitor);
    const testRows      = activeEntries.filter(e => !e.is_monitor);
    const hygieneRows   = termDiff.hygiene_entries || [];

    const statusColor = {
        passed: '#22c55e', failed: '#ef4444', warning: '#f59e0b',
        error: '#94a3b8', not_run: '#6b7280',
    };
    const likelihoodColor = { Definite: '#ef4444', Likely: '#f59e0b', Possible: '#94a3b8' };

    const StatusChip = (color, label) =>
        span({ class: 'compliance-chip', style: `background:${color}` }, label);

    const ComplianceRow = (entry) =>
        div(
            { class: 'compliance-row' },
            span({ class: 'diff-element' }, entry.element),
            span({ class: 'diff-test-type' }, entry.test_type || ''),
            StatusChip(
                statusColor[entry.last_result] || '#6b7280',
                (entry.last_result || 'not run').replace('_', ' '),
            ),
        );

    const HygieneRow = (entry) =>
        div(
            { class: 'compliance-row' },
            span({ class: 'diff-element' }, entry.element),
            span({ class: 'diff-test-type' }, entry.anomaly_type || ''),
            StatusChip(likelihoodColor[entry.issue_likelihood] || '#94a3b8', entry.issue_likelihood || ''),
        );

    const headerStr = (pairs) =>
        pairs.filter(([, n]) => n > 0).map(([lbl, n]) => `${n} ${lbl}`).join('  ');

    const monitorHeader = headerStr([
        ['passed', termDiff.tg_monitor_passed], ['failed', termDiff.tg_monitor_failed],
        ['warning', termDiff.tg_monitor_warning], ['error', termDiff.tg_monitor_error],
        ['not run', termDiff.tg_monitor_not_run],
    ]);
    const testHeader = headerStr([
        ['passed', termDiff.tg_test_passed], ['failed', termDiff.tg_test_failed],
        ['warning', termDiff.tg_test_warning], ['error', termDiff.tg_test_error],
        ['not run', termDiff.tg_test_not_run],
    ]);
    const hygieneHeader = headerStr([
        ['definite', termDiff.tg_hygiene_definite], ['likely', termDiff.tg_hygiene_likely],
        ['possible', termDiff.tg_hygiene_possible],
    ]);

    const ComplianceAccordion = (label, rows, headerSummary) => {
        if (rows.length === 0) return '';
        const isOpen = van.state(true);
        return div(
            { class: 'diff-accordion' },
            div(
                {
                    class: 'diff-accordion-header',
                    onclick: () => { isOpen.val = !isOpen.val; },
                },
                () => mat(isOpen.val ? 'expand_more' : 'chevron_right', 14),
                ` ${label}`,
                headerSummary
                    ? span({ class: 'accordion-header-stats' }, `  ${headerSummary}`)
                    : '',
            ),
            () => isOpen.val
                ? div({ class: 'diff-accordion-body' }, ...rows)
                : '',
        );
    };

    return div(
        { class: 'dc-compliance-tab' },
        ComplianceAccordion('Monitors', monitorRows.map(ComplianceRow), monitorHeader),
        ComplianceAccordion('Tests',    testRows.map(ComplianceRow),    testHeader),
        ComplianceAccordion('Hygiene',  hygieneRows.map(HygieneRow),    hygieneHeader),
    );
};
```

- [ ] **Step 2: Add CSS for the Compliance tab**

Append to the `stylesheet` template literal:

```css
/* ── Compliance tab ── */
.dc-compliance-tab { padding: 16px 0; }
.compliance-row {
    display: flex; align-items: center; gap: 10px; padding: 5px 18px;
    font-size: 12px; border-bottom: 1px solid rgba(255,255,255,0.04);
}
.compliance-row:last-child { border-bottom: none; }
.compliance-chip {
    font-size: 10px; font-weight: 600; color: #fff;
    border-radius: 3px; padding: 1px 6px; white-space: nowrap;
    text-transform: lowercase;
}
.accordion-header-stats { font-size: 11px; font-weight: 400; color: #64748b; }
```

- [ ] **Step 3: Verify the Compliance tab renders**

Open the Data Contract page, click "Contract Term Compliance" tab. The three accordions (Monitors / Tests / Hygiene) should appear with per-term rows and status chips.

- [ ] **Step 4: Commit Tasks 4 and 5 together**

```bash
git add testgen/ui/components/frontend/js/pages/data_contract.js
git commit -m "feat: add DifferencesTab and ComplianceTab to data contract page"
```

---

## Manual End-to-End Test Checklist

After all tasks are complete:

- [ ] Coverage card label reads "Contract Term Coverage" (content unchanged)
- [ ] Coverage card still links to Coverage Matrix tab
- [ ] Card 2 shows "Version N Contract Term Differences" with Saved/Current counts and status rows
- [ ] Clicking a status row on Card 2 navigates to Differences tab with that accordion open
- [ ] Card 3 shows "Version N Contract Term Compliance" with tier table and monitor/test/hygiene chips
- [ ] "Contract Term Coverage" tab label is updated (tab content unchanged)
- [ ] "Contract Term Differences" tab shows 4 accordions; Changed/New/Deleted expanded, Same collapsed
- [ ] "Contract Term Compliance" tab shows Monitors / Tests / Hygiene accordions
- [ ] No console errors in browser DevTools
- [ ] No Python tracebacks in terminal when loading the page
