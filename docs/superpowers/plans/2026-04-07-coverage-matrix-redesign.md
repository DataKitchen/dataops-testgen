# Coverage Matrix Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the binary covered/uncovered model with a three-tier enforcement model (TestGen Enforced / DB Enforced / Unenforced / Uncovered) surfaced in both the Contract Completeness health card and the Coverage Matrix tab.

**Architecture:** New Python helpers classify each element into exactly one tier; tier counts flow through the existing `health` dict to the JS `HealthGrid` component; the JS `CoverageMatrix` component gains completeness bars at the top, per-table accordion pills, and a reordered + extended matrix table with an Uncovered flag column.

**Tech Stack:** Python 3.12, VanJS (no framework), existing `data_contract_props.py` / `data_contract.js` patterns.

---

## File Map

| File | Change |
|------|--------|
| `testgen/ui/views/data_contract_props.py` | Add `_classify_enforcement_tier`, `_has_meaningful_ddl_constraint`, `_has_unenforced_terms`; update health dict; add `tier` to matrix rows; remove `_is_covered` |
| `testgen/ui/views/data_contract.py` | Export new helpers; update `_render_health_dashboard` to use tier counts |
| `testgen/ui/components/frontend/js/pages/data_contract.js` | Update `HealthGrid` coverage card; rewrite `CoverageMatrix` and `MatrixTableSection` |
| `tests/unit/ui/test_data_contract_page.py` | Tests for new tier helpers and health dict fields |

---

## Task 1 — Tier classification helpers (TDD)

**Files:**
- Modify: `testgen/ui/views/data_contract_props.py`
- Modify: `tests/unit/ui/test_data_contract_page.py`

- [ ] **Step 1: Write failing tests**

Add a new test class to `tests/unit/ui/test_data_contract_page.py` after `Test_ColumnCoverageTiers`:

```python
# ---------------------------------------------------------------------------
# NEW: Enforcement tier classification
# ---------------------------------------------------------------------------

class Test_ClassifyEnforcementTier:
    """_classify_enforcement_tier assigns each element to exactly one tier."""

    def _prop(self, physical="text", **kwargs):
        return {"physicalType": physical, "name": "col", **kwargs}

    def _rule(self, test_type="columnType"):
        return {"testType": test_type, "element": "tbl.col", "lastResult": {}}

    # ── TestGen enforced ────────────────────────────────────────────────────

    def test_column_with_test_is_tg(self):
        assert _classify_enforcement_tier(self._prop(), [self._rule()]) == "tg"

    def test_column_with_monitor_is_tg(self):
        assert _classify_enforcement_tier(self._prop(), [self._rule("Volume_Trend")]) == "tg"

    def test_tg_beats_meaningful_ddl(self):
        prop = self._prop("varchar(50)", required=True)
        assert _classify_enforcement_tier(prop, [self._rule()]) == "tg"

    # ── DB enforced ─────────────────────────────────────────────────────────

    def test_not_null_no_tests_is_db(self):
        prop = self._prop("text", required=True)
        assert _classify_enforcement_tier(prop, []) == "db"

    def test_nullable_false_is_db(self):
        prop = self._prop("text", nullable=False)
        assert _classify_enforcement_tier(prop, []) == "db"

    def test_pk_no_tests_is_db(self):
        prop = self._prop("integer", logicalTypeOptions={"primaryKey": True})
        assert _classify_enforcement_tier(prop, []) == "db"

    def test_varchar_constrained_no_tests_is_db(self):
        assert _classify_enforcement_tier(self._prop("varchar(100)"), []) == "db"

    def test_numeric_precision_no_tests_is_db(self):
        assert _classify_enforcement_tier(self._prop("decimal(10,2)"), []) == "db"

    def test_fk_no_tests_is_db(self):
        prop = self._prop("bigint")
        assert _classify_enforcement_tier(prop, [], col_refs=[{"to": "other_table.id"}]) == "db"

    # ── Unenforced ──────────────────────────────────────────────────────────

    def test_description_no_tests_no_ddl_is_unf(self):
        prop = self._prop("text", description="some description")
        assert _classify_enforcement_tier(prop, []) == "unf"

    def test_classification_no_tests_no_ddl_is_unf(self):
        prop = self._prop("text", classification="pii")
        assert _classify_enforcement_tier(prop, []) == "unf"

    def test_cde_no_tests_no_ddl_is_unf(self):
        prop = self._prop("text", criticalDataElement=True)
        assert _classify_enforcement_tier(prop, []) == "unf"

    def test_format_no_tests_no_ddl_is_unf(self):
        prop = self._prop("text", logicalTypeOptions={"format": "EMAIL"})
        assert _classify_enforcement_tier(prop, []) == "unf"

    def test_min_stat_no_tests_no_ddl_is_unf(self):
        prop = self._prop("text", logicalTypeOptions={"minimum": 0})
        assert _classify_enforcement_tier(prop, []) == "unf"

    def test_gov_col_description_is_unf(self):
        prop = self._prop("text")
        gov = {"description": "live description"}
        assert _classify_enforcement_tier(prop, [], gov_col=gov) == "unf"

    # ── Uncovered ────────────────────────────────────────────────────────────

    def test_bare_text_no_anything_is_none(self):
        assert _classify_enforcement_tier(self._prop("text"), []) == "none"

    def test_bare_timestamp_no_constraints_is_none(self):
        assert _classify_enforcement_tier(self._prop("timestamp"), []) == "none"

    def test_bare_integer_no_constraints_is_none(self):
        assert _classify_enforcement_tier(self._prop("integer"), []) == "none"

    # ── Tier precedence ──────────────────────────────────────────────────────

    def test_description_with_meaningful_ddl_is_db_not_unf(self):
        """DB beats Unenforced even when unenforced terms also exist."""
        prop = self._prop("varchar(50)", description="some desc")
        assert _classify_enforcement_tier(prop, []) == "db"
```

Update the imports at the top of the test file to add the new helpers. The import block currently reads:

```python
from testgen.ui.views.data_contract import (  # noqa: E402
    DataContractPage,
    _build_contract_props,
    _column_coverage_tiers,
    _tier_badge,
    _quality_counts,
    _worst_status,
    ContractDiff as _ContractDiff,
)
```

Change to:

```python
from testgen.ui.views.data_contract import (  # noqa: E402
    DataContractPage,
    _build_contract_props,
    _classify_enforcement_tier,
    _column_coverage_tiers,
    _tier_badge,
    _quality_counts,
    _worst_status,
    ContractDiff as _ContractDiff,
)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source venv/bin/activate
pytest tests/unit/ui/test_data_contract_page.py::Test_ClassifyEnforcementTier -v 2>&1 | head -30
```

Expected: `ImportError` or `AttributeError` — `_classify_enforcement_tier` does not exist yet.

- [ ] **Step 3: Add helpers to `data_contract_props.py`**

In `data_contract_props.py`, after the `_is_covered` function (around line 168), add:

```python
# ---------------------------------------------------------------------------
# Enforcement tier classification — replaces the binary _is_covered model
# ---------------------------------------------------------------------------

def _has_meaningful_ddl_constraint(prop: dict, col_refs: list[dict] | None = None) -> bool:
    """True when a column has a DB-enforced constraint beyond its bare data type.

    Counts: NOT NULL / required, Primary Key, Foreign Key,
    char-constrained types (VARCHAR(n)), numeric-precision types (DECIMAL(p,s)).
    Does NOT count bare integer / timestamp / boolean types alone.
    """
    opts = prop.get("logicalTypeOptions") or {}
    if prop.get("required") or prop.get("nullable") is False:
        return True
    if opts.get("primaryKey"):
        return True
    if col_refs:
        return True
    physical_lower = (prop.get("physicalType") or "").lower().strip()
    return bool(
        _CHAR_CONSTRAINED_RE.match(physical_lower)
        or _NUMERIC_PREC_RE.match(physical_lower)
    )


def _has_unenforced_terms(prop: dict, gov_col: dict | None = None) -> bool:
    """True when a column has observed stats or declared governance metadata."""
    opts = prop.get("logicalTypeOptions") or {}
    gov  = gov_col or {}
    return bool(
        prop.get("classification")
        or prop.get("criticalDataElement")
        or prop.get("description")
        or gov.get("description")
        or gov.get("pii_flag")
        or gov.get("critical_data_element")
        or gov.get("excluded_data_element")
        or opts.get("format")
        or opts.get("minimum") is not None
        or opts.get("maximum") is not None
        or opts.get("minLength") is not None
        or opts.get("maxLength") is not None
    )


def _classify_enforcement_tier(
    prop: dict,
    col_rules: list[dict],
    gov_col: dict | None = None,
    col_refs: list[dict] | None = None,
) -> str:
    """Assign the highest enforcement tier to a column or table-level element.

    Returns one of: "tg" | "db" | "unf" | "none"

    Hierarchy (highest wins):
    - "tg"  : has at least one TestGen test or monitor
    - "db"  : has a meaningful DDL constraint (NOT NULL, PK, FK, VARCHAR(n), DECIMAL(p,s))
    - "unf" : has observed profiling stats or declared governance metadata
    - "none": only a bare data type — nothing richer
    """
    if col_rules:
        return "tg"
    if _has_meaningful_ddl_constraint(prop, col_refs):
        return "db"
    if _has_unenforced_terms(prop, gov_col):
        return "unf"
    return "none"
```

- [ ] **Step 4: Export `_classify_enforcement_tier` from `data_contract.py`**

Open `testgen/ui/views/data_contract.py`. The import block from `data_contract_props` (around line 44) currently is:

```python
from testgen.ui.views.data_contract_props import (
    _build_contract_props,
    _column_coverage_tiers,
    _quality_counts,
    _tier_badge,
    _worst_status,
)
```

Change to:

```python
from testgen.ui.views.data_contract_props import (
    _build_contract_props,
    _classify_enforcement_tier,
    _column_coverage_tiers,
    _quality_counts,
    _tier_badge,
    _worst_status,
)
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/unit/ui/test_data_contract_page.py::Test_ClassifyEnforcementTier -v
```

Expected: all tests in `Test_ClassifyEnforcementTier` pass.

- [ ] **Step 6: Commit**

```bash
git add testgen/ui/views/data_contract_props.py testgen/ui/views/data_contract.py tests/unit/ui/test_data_contract_page.py
git commit -m "feat: add enforcement tier classification helpers"
```

---

## Task 2 — Tier counts in health dict (TDD)

**Files:**
- Modify: `testgen/ui/views/data_contract_props.py`
- Modify: `tests/unit/ui/test_data_contract_page.py`

- [ ] **Step 1: Write failing test**

Add this class to `tests/unit/ui/test_data_contract_page.py` after `Test_ClassifyEnforcementTier`:

```python
class Test_HealthTierCounts:
    """_build_contract_props health dict includes tier counts."""

    def _minimal_doc(self, tables):
        return {"schema": tables, "quality": [], "references": []}

    def _table(self, name, columns):
        return {"name": name, "properties": columns}

    def _col(self, name, physical="text", **kwargs):
        return {"name": name, "physicalType": physical, **kwargs}

    def test_health_has_tier_keys(self):
        doc = self._minimal_doc([self._table("t", [self._col("a")])])
        from unittest.mock import MagicMock, patch
        tg = MagicMock()
        tg.id = "00000000-0000-0000-0000-000000000001"
        with patch("testgen.ui.views.data_contract_props._fetch_governance_data", return_value={}):
            props = _build_contract_props(doc, [], tg, gov_by_col={})
        h = props["health"]
        assert "tg_enforced"  in h
        assert "db_enforced"  in h
        assert "unenforced"   in h
        assert "uncovered"    in h
        assert "n_elements"   in h

    def test_n_elements_is_columns_plus_tables(self):
        doc = self._minimal_doc([
            self._table("t1", [self._col("a"), self._col("b")]),
            self._table("t2", [self._col("c")]),
        ])
        from unittest.mock import MagicMock, patch
        tg = MagicMock()
        tg.id = "00000000-0000-0000-0000-000000000001"
        with patch("testgen.ui.views.data_contract_props._fetch_governance_data", return_value={}):
            props = _build_contract_props(doc, [], tg, gov_by_col={})
        # 3 columns + 2 table-level rows = 5
        assert props["health"]["n_elements"] == 5

    def test_tier_counts_sum_to_n_elements(self):
        doc = self._minimal_doc([
            self._table("t", [
                self._col("id", "integer", required=True),        # db
                self._col("notes", "text"),                        # none
                self._col("email", "text", description="Email"),  # unf
            ]),
        ])
        from unittest.mock import MagicMock, patch
        tg = MagicMock()
        tg.id = "00000000-0000-0000-0000-000000000001"
        with patch("testgen.ui.views.data_contract_props._fetch_governance_data", return_value={}):
            props = _build_contract_props(doc, [], tg, gov_by_col={})
        h = props["health"]
        total = h["tg_enforced"] + h["db_enforced"] + h["unenforced"] + h["uncovered"]
        assert total == h["n_elements"]

    def test_column_with_test_rule_counted_as_tg(self):
        rule = {"id": "r1", "testType": "columnType", "element": "t.id", "lastResult": {"status": "passing"}}
        doc = self._minimal_doc([self._table("t", [self._col("id", "integer")])])
        doc["quality"] = [rule]
        from unittest.mock import MagicMock, patch
        tg = MagicMock()
        tg.id = "00000000-0000-0000-0000-000000000001"
        with patch("testgen.ui.views.data_contract_props._fetch_governance_data", return_value={}):
            props = _build_contract_props(doc, [], tg, gov_by_col={})
        assert props["health"]["tg_enforced"] >= 1
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/ui/test_data_contract_page.py::Test_HealthTierCounts -v 2>&1 | head -30
```

Expected: `KeyError` or `AssertionError` — `tg_enforced` not in health dict.

- [ ] **Step 3: Update health dict computation in `_build_contract_props`**

In `data_contract_props.py`, find the `health` dict construction (around line 444). The block that computes `covered`, `coverage_pct`, and builds `all_props` looks like:

```python
all_props = [(t.get("name", ""), p) for t in schema for p in (t.get("properties") or [])]
n_cols = len(all_props)

rules_by_element: dict[str, list[dict]] = {}
for rule in quality:
    rules_by_element.setdefault(rule.get("element", ""), []).append(rule)

covered = sum(
    1 for tbl, prop in all_props
    if _is_covered(
        prop,
        rules_by_element.get(f"{tbl}.{prop.get('name', '')}", [])
        + rules_by_element.get(prop.get("name", ""), []),
    )
)
coverage_pct = int(100 * covered / n_cols) if n_cols else 0
```

Replace that entire block with:

```python
all_props = [(t.get("name", ""), p) for t in schema for p in (t.get("properties") or [])]

rules_by_element: dict[str, list[dict]] = {}
for rule in quality:
    rules_by_element.setdefault(rule.get("element", ""), []).append(rule)

# --- Tier counts (columns + one table-level element per table) ---
tier_counts: dict[str, int] = {"tg": 0, "db": 0, "unf": 0, "none": 0}

# Column-level tiers
for tbl, prop in all_props:
    col_name  = prop.get("name", "")
    col_key   = f"{tbl}.{col_name}"
    col_rules = (
        rules_by_element.get(col_key, [])
        + rules_by_element.get(col_name, [])
    )
    tier = _classify_enforcement_tier(prop, col_rules)
    tier_counts[tier] += 1

# Table-level tiers (one per table — tg if has any test/monitor, else none)
for t in schema:
    tbl_name  = t.get("name", "")
    tbl_rules = rules_by_element.get(tbl_name, [])
    tbl_tier  = "tg" if tbl_rules else "none"
    tier_counts[tbl_tier] += 1

n_elements = sum(tier_counts.values())

# Keep legacy fields for the Streamlit preview flow
n_cols       = len(all_props)
covered      = tier_counts["tg"] + tier_counts["db"] + tier_counts["unf"]
coverage_pct = int(100 * covered / n_elements) if n_elements else 0
```

Then add the new keys to the `health` dict. Find the `health = {` block and add after `"n_cols": n_cols,`:

```python
        "tg_enforced":  tier_counts["tg"],
        "db_enforced":  tier_counts["db"],
        "unenforced":   tier_counts["unf"],
        "uncovered":    tier_counts["none"],
        "n_elements":   n_elements,
```

The full updated `health = {` block should look like:

```python
    health = {
        "coverage_pct":          coverage_pct,
        "covered":               covered,
        "n_cols":                n_cols,
        "tg_enforced":           tier_counts["tg"],
        "db_enforced":           tier_counts["db"],
        "unenforced":            tier_counts["unf"],
        "uncovered":             tier_counts["none"],
        "n_elements":            n_elements,
        "n_tests":               len(quality),
        "passing":               counts.get("passing", 0),
        "warning":               counts.get("warning", 0),
        "failing":               counts.get("failing", 0) + counts.get("error", 0),
        "not_run":               counts.get("not run", 0),
        "hygiene_total":         len(anomalies),
        "hygiene_definite":      sum(1 for a in anomalies if a.get("issue_likelihood") == "Definite"),
        "hygiene_likely":        sum(1 for a in anomalies if a.get("issue_likelihood") == "Likely"),
        "hygiene_possible":      sum(1 for a in anomalies if a.get("issue_likelihood") == "Possible"),
        "last_test_run":         _fmt_ts(rd.get("last_test_run")),
        "last_test_run_id":      str(rd["last_test_run_id"]) if rd.get("last_test_run_id") else None,
        "last_profiling_run":    _fmt_ts(rd.get("last_profiling_run")),
        "last_profiling_run_id": str(rd["last_profiling_run_id"]) if rd.get("last_profiling_run_id") else None,
        "suites_included":       len(_scope.get("included", [])),
        "suites_total":          _scope.get("total", 0),
        "suite_runs": [
            {
                "suite_id":   sr["suite_id"],
                "suite_name": sr["suite_name"],
                "run_id":     sr["run_id"],
                "run_start":  _fmt_ts(sr.get("run_start")),
                "test_ct":    int(sr.get("test_ct") or 0),
                "passed_ct":  int(sr.get("passed_ct") or 0),
                "warning_ct": int(sr.get("warning_ct") or 0),
                "failed_ct":  int(sr.get("failed_ct") or 0),
                "error_ct":   int(sr.get("error_ct") or 0),
            }
            for sr in rd.get("suite_runs", [])
        ],
    }
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/unit/ui/test_data_contract_page.py::Test_HealthTierCounts -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Run full unit suite to confirm no regressions**

```bash
pytest tests/unit/ui/test_data_contract_page.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add testgen/ui/views/data_contract_props.py tests/unit/ui/test_data_contract_page.py
git commit -m "feat: add tier counts (tg_enforced/db_enforced/unenforced/uncovered) to health dict"
```

---

## Task 3 — Add `tier` field to matrix rows (TDD)

**Files:**
- Modify: `testgen/ui/views/data_contract_props.py`
- Modify: `tests/unit/ui/test_data_contract_page.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/ui/test_data_contract_page.py`:

```python
class Test_MatrixRowTier:
    """Each matrix row must carry a 'tier' field."""

    def _doc_with_col(self, col_physical="text", col_kwargs=None, rules=None):
        col = {"name": "c1", "physicalType": col_physical, **(col_kwargs or {})}
        doc = {"schema": [{"name": "tbl", "properties": [col]}], "quality": rules or [], "references": []}
        return doc

    def _build(self, doc):
        from unittest.mock import MagicMock, patch
        tg = MagicMock()
        tg.id = "00000000-0000-0000-0000-000000000001"
        with patch("testgen.ui.views.data_contract_props._fetch_governance_data", return_value={}):
            return _build_contract_props(doc, [], tg, gov_by_col={})

    def test_matrix_rows_have_tier(self):
        props = self._build(self._doc_with_col())
        for row in props["coverage_matrix"]:
            assert "tier" in row, f"row missing 'tier': {row}"

    def test_column_with_test_has_tg_tier(self):
        rule = {"id": "r1", "testType": "noNulls", "element": "tbl.c1", "lastResult": {"status": "passing"}}
        props = self._build(self._doc_with_col(rules=[rule]))
        col_rows = [r for r in props["coverage_matrix"] if r["column"] == "c1"]
        assert col_rows[0]["tier"] == "tg"

    def test_bare_text_column_has_none_tier(self):
        props = self._build(self._doc_with_col("text"))
        col_rows = [r for r in props["coverage_matrix"] if r["column"] == "c1"]
        assert col_rows[0]["tier"] == "none"

    def test_varchar_constrained_no_tests_has_db_tier(self):
        props = self._build(self._doc_with_col("varchar(50)"))
        col_rows = [r for r in props["coverage_matrix"] if r["column"] == "c1"]
        assert col_rows[0]["tier"] == "db"

    def test_table_level_row_with_tests_has_tg_tier(self):
        rule = {"id": "r1", "testType": "rowCount", "element": "tbl", "lastResult": {"status": "passing"}}
        props = self._build(self._doc_with_col(rules=[rule]))
        tbl_rows = [r for r in props["coverage_matrix"] if r["column"] == "(table-level)"]
        assert tbl_rows[0]["tier"] == "tg"

    def test_table_level_row_without_tests_has_none_tier(self):
        props = self._build(self._doc_with_col())
        tbl_rows = [r for r in props["coverage_matrix"] if r["column"] == "(table-level)"]
        assert tbl_rows[0]["tier"] == "none"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/ui/test_data_contract_page.py::Test_MatrixRowTier -v 2>&1 | head -20
```

Expected: `AssertionError` — `tier` not in row dict.

- [ ] **Step 3: Add `tier` to matrix rows in `_build_contract_props`**

In `data_contract_props.py`, find the matrix row builder for table-level rows (around line 492):

```python
            matrix_rows.append({
                "table":  table_name,
                "column": "(table-level)",
                "db":     0,
                "tested": tbl_test,
                "mon":    tbl_mon,
                "obs":    0,
                "decl":   0,
            })
```

Change to:

```python
            matrix_rows.append({
                "table":  table_name,
                "column": "(table-level)",
                "db":     0,
                "tested": tbl_test,
                "mon":    tbl_mon,
                "obs":    0,
                "decl":   0,
                "tier":   "tg",
            })
```

For column rows, find the block (around line 545):

```python
            matrix_rows.append({
                "table":  table_name,
                "column": col_name,
                "db":     db_ct,
                "tested": tested_ct,
                "mon":    mon_ct,
                "obs":    obs_ct,
                "decl":   decl_ct,
            })
```

Change to:

```python
            gov_col_for_tier = effective_gov.get((table_name, col_name)) or {}
            matrix_rows.append({
                "table":  table_name,
                "column": col_name,
                "db":     db_ct,
                "tested": tested_ct,
                "mon":    mon_ct,
                "obs":    obs_ct,
                "decl":   decl_ct,
                "tier":   _classify_enforcement_tier(
                              prop, col_rules,
                              gov_col=gov_col_for_tier,
                              col_refs=col_refs,
                          ),
            })
```

For table-level rows without tests (currently skipped when `tbl_rules_mx` is empty), they don't appear in `matrix_rows` at all. Update the condition so table-level rows always appear:

Find (around line 488):

```python
        tbl_rules_mx = rules_by_element_full.get(table_name, [])
        if tbl_rules_mx:
            tbl_mon  = sum(1 for r in tbl_rules_mx if r.get("testType", "") in _MONITOR_TEST_TYPES)
            tbl_test = sum(1 for r in tbl_rules_mx if r.get("testType", "") not in _MONITOR_TEST_TYPES)
            matrix_rows.append({...})
```

Change to:

```python
        tbl_rules_mx = rules_by_element_full.get(table_name, [])
        tbl_mon  = sum(1 for r in tbl_rules_mx if r.get("testType", "") in _MONITOR_TEST_TYPES)
        tbl_test = sum(1 for r in tbl_rules_mx if r.get("testType", "") not in _MONITOR_TEST_TYPES)
        matrix_rows.append({
            "table":  table_name,
            "column": "(table-level)",
            "db":     0,
            "tested": tbl_test,
            "mon":    tbl_mon,
            "obs":    0,
            "decl":   0,
            "tier":   "tg" if tbl_rules_mx else "none",
        })
```

- [ ] **Step 4: Run tests — expect pass**

```bash
pytest tests/unit/ui/test_data_contract_page.py::Test_MatrixRowTier -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/unit/ui/test_data_contract_page.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add testgen/ui/views/data_contract_props.py tests/unit/ui/test_data_contract_page.py
git commit -m "feat: add tier field to coverage matrix rows"
```

---

## Task 4 — Update `HealthGrid` coverage card in JS (four bars)

**Files:**
- Modify: `testgen/ui/components/frontend/js/pages/data_contract.js`

- [ ] **Step 1: Replace the coverage card in `HealthGrid`**

In `data_contract.js`, find the `HealthGrid` function (around line 774). Find the coverage card block — it starts at:

```javascript
        // — Coverage card
        div(
            {
                class: 'health-card coverage health-card--link',
                onclick: () => { activeTab.val = 'matrix'; },
                title: 'View Coverage Matrix',
            },
            div({ class: 'health-card__label' },
                mat('verified', 13), ' Contract Completeness',
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
            div({ class: `health-card__value ${coverageCls}` }, `${health.coverage_pct}%`),
            div({ class: 'progress-track' },
                div({ class: `progress-fill ${coverageCls}`, style: `width:${health.coverage_pct}%` }),
            ),
            div({ class: 'health-card__sub' }, `${health.covered} of ${health.n_cols} columns have ≥1 non-schema term`),
            health.n_cols - health.covered > 0
                ? filterButton(`View ${health.n_cols - health.covered} uncovered →`, 'uncovered')
                : '',
        ),
```

Replace it with:

```javascript
        // — Coverage card (four-tier bars)
        div(
            {
                class: 'health-card coverage health-card--link',
                onclick: () => { activeTab.val = 'matrix'; },
                title: 'View Coverage Matrix',
            },
            div({ class: 'health-card__label' },
                mat('verified', 13), ' Contract Completeness',
                span({ class: 'health-card__nav-icon' }, mat('open_in_new', 11)),
            ),
            CoverageTierBars(health, /* compact */ true),
        ),
```

- [ ] **Step 2: Add the `CoverageTierBars` helper above `HealthGrid`**

Insert this function immediately before `const HealthGrid = ` (around line 772):

```javascript
// ── Coverage tier bars — shared by health card and matrix tab ─────────────────

const COVERAGE_TIERS = [
    { key: 'tg_enforced', label: '⚡ TestGen Enforced', color: '#22c55e', textColor: '#4ade80' },
    { key: 'db_enforced', label: '🏛 DB Enforced only', color: '#818cf8', textColor: '#a5b4fc' },
    { key: 'unenforced',  label: '📋 Unenforced only',  color: '#f59e0b', textColor: '#fbbf24' },
    { key: 'uncovered',   label: '○ Uncovered',         color: '#4b5563', textColor: '#6b7280' },
];

const CoverageTierBars = (health, compact = false, onTierClick = null) => {
    const n = health.n_elements || health.n_cols || 1;
    return div(
        { class: compact ? 'ctbars ctbars--compact' : 'ctbars' },
        ...COVERAGE_TIERS.map(({ key, label, color, textColor }) => {
            const count = health[key] || 0;
            const pct   = Math.round((count / n) * 100);
            return div(
                {
                    class: 'ctbars__row',
                    style: onTierClick ? 'cursor:pointer' : '',
                    onclick: onTierClick ? () => onTierClick(key) : undefined,
                },
                div({ class: 'ctbars__label' }, label),
                div(
                    { class: 'ctbars__track' },
                    div({ class: 'ctbars__fill', style: `width:${pct}%;background:${color}` }),
                ),
                div({ class: 'ctbars__count', style: `color:${textColor}` }, `${count} / ${n}`),
            );
        }),
    );
};
```

- [ ] **Step 3: Remove the now-unused `coverageCls` variable at the top of `HealthGrid`**

In `HealthGrid`, the first line is:

```javascript
    const coverageCls = health.coverage_pct >= 80 ? 'good' : health.coverage_pct >= 50 ? 'warn' : 'bad';
```

Remove that line entirely (no other part of `HealthGrid` uses `coverageCls` after this change).

- [ ] **Step 4: Add CSS for tier bars**

In the stylesheet (at the bottom of the file, inside `stylesheet.replace(`), add after `.health-card.coverage::before { ... }`:

```css
/* ── Coverage tier bars ── */
.ctbars { padding: 4px 0 2px; }
.ctbars--compact { padding: 2px 0; }
.ctbars__row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
}
.ctbars--compact .ctbars__row { margin-bottom: 5px; }
.ctbars__row:last-child { margin-bottom: 0; }
.ctbars__label {
    width: 156px;
    flex-shrink: 0;
    font-size: 11px;
    font-weight: 600;
    color: #94a3b8;
    white-space: nowrap;
}
.ctbars--compact .ctbars__label { font-size: 10px; width: 140px; }
.ctbars__track {
    flex: 1;
    height: 6px;
    background: #2d3348;
    border-radius: 3px;
    overflow: hidden;
}
.ctbars--compact .ctbars__track { height: 5px; }
.ctbars__fill { height: 100%; border-radius: 3px; transition: width 0.2s; }
.ctbars__count {
    width: 52px;
    text-align: right;
    font-size: 11px;
    font-weight: 600;
    flex-shrink: 0;
}
.ctbars--compact .ctbars__count { font-size: 10px; width: 44px; }

/* Filter state — dim non-active rows */
.ctbars__row.tier-inactive { opacity: 0.3; }
```

- [ ] **Step 5: Manual verification**

Start the UI and navigate to a data contract page:

```bash
source venv/bin/activate && testgen run-app ui
```

Open `http://localhost:8501` → navigate to a table group's data contract. The Contract Completeness health card should now show four stacked bars instead of a percentage + single bar. Clicking the card navigates to the matrix tab.

- [ ] **Step 6: Commit**

```bash
git add testgen/ui/components/frontend/js/pages/data_contract.js
git commit -m "feat: replace health card coverage bar with four-tier stacked bars"
```

---

## Task 5 — Rewrite `CoverageMatrix` tab

**Files:**
- Modify: `testgen/ui/components/frontend/js/pages/data_contract.js`

This task rewrites `CoverageMatrix` and `MatrixTableSection`. Do it in two sub-steps.

### 5a — Update `MATRIX_COLS` and `MatrixTableSection`

- [ ] **Step 1: Replace `MATRIX_COLS`**

Find and replace the `MATRIX_COLS` constant:

```javascript
const MATRIX_COLS = [
    { key: 'db',     label: '🏛️ DB Enforced' },
    { key: 'tested', label: '⚡ Tested'       },
    { key: 'mon',    label: '📡 Monitored'    },
    { key: 'obs',    label: '📸 Observed'     },
    { key: 'decl',   label: '🏷️ Declared'    },
];
```

Replace with:

```javascript
// Ordered: most valuable enforcement left, flag right.
// Groups: TestGen (tested, mon) | DB (db) | Unenforced (obs, decl) | Uncovered flag
const MATRIX_COLS = [
    { key: 'tested', label: 'Tests',    group: 'tg'  },
    { key: 'mon',    label: 'Monitors', group: 'tg'  },
    { key: 'db',     label: 'DDL',      group: 'db'  },
    { key: 'obs',    label: 'Observed', group: 'unf' },
    { key: 'decl',   label: 'Declared', group: 'unf' },
];

const MATRIX_GROUPS = [
    { key: 'tg',  label: '⚡ TestGen Enforced', span: 2, color: '#22c55e' },
    { key: 'db',  label: '🏛 DB Enforced',       span: 1, color: '#818cf8' },
    { key: 'unf', label: '📋 Unenforced',         span: 2, color: '#f59e0b' },
];

const TIER_DOT_COLOR = {
    tg:   '#22c55e',
    db:   '#818cf8',
    unf:  '#f59e0b',
    none: '#374151',
};
```

- [ ] **Step 2: Rewrite `MatrixTableSection`**

Replace the entire `MatrixTableSection` function (from `const MatrixTableSection = ` through the closing `};`) with:

```javascript
const MatrixTableSection = (tableName, rows, startOpen, totals) => {
    const open = van.state(startOpen);

    // Per-table tier pill counts
    const tierCounts = { tg: 0, db: 0, unf: 0, none: 0 };
    for (const r of rows) tierCounts[r.tier || 'none']++;

    const TierPill = (tierKey, color, labelText) => {
        const n = tierCounts[tierKey];
        return span(
            { class: 'matrix-tier-pill', style: `--pill-color:${color}` },
            labelText, ' ', n,
        );
    };

    const pillsBar = div(
        { class: () => `matrix-pills-bar${open.val ? ' matrix-pills-bar--hidden' : ''}` },
        TierPill('tg',   '#4ade80', '⚡'),
        TierPill('db',   '#a5b4fc', '🏛'),
        TierPill('unf',  '#fbbf24', '📋'),
        TierPill('none', '#6b7280', '○'),
    );

    const ColDot = (tier) =>
        span({ class: 'col-tier-dot', style: `background:${TIER_DOT_COLOR[tier] || TIER_DOT_COLOR.none}` });

    const matrixTable = table(
        { class: 'matrix-table matrix-table--tiers' },
        thead(
            // Group header row
            tr(
                th({ class: 'col-col' }),
                ...MATRIX_GROUPS.map((g) =>
                    th({ class: `group-th group-th--${g.key}`, colspan: g.span, style: `color:${g.color}` }, g.label),
                ),
                th({ class: 'group-th group-th--unc' }, 'Uncovered'),
            ),
            // Sub-header row
            tr(
                th({ class: 'col-col' }, 'Column'),
                ...MATRIX_COLS.map((c) => th({ class: `tier-col tier-col--${c.group}`, title: c.label }, c.label)),
                th({ class: 'tier-col tier-col--unc' }),
            ),
        ),
        tbody(
            ...rows.map((row) => tr(
                { 'data-tier': row.tier || 'none' },
                td(
                    { class: row.column === '(table-level)' ? 'col-name col-name--table' : 'col-name' },
                    ColDot(row.tier || 'none'),
                    row.column,
                ),
                ...MATRIX_COLS.map((c) => td(
                    { class: `tier-cell tier-cell--${c.group} ${(row[c.key] || 0) > 0 ? 'has-terms' : 'no-terms'}` },
                    fmtCount(row[c.key] || 0),
                )),
                // Uncovered flag cell
                td(
                    { class: 'tier-cell tier-cell--unc' },
                    (row.tier || 'none') === 'none'
                        ? span({ class: 'uncov-yes' }, 'Yes')
                        : '',
                ),
            )),
            tr(
                { class: 'matrix-totals-row' },
                td('Totals'),
                ...MATRIX_COLS.map((c) => td({ class: 'tier-cell' }, fmtCount(totals[c.key]))),
                td(),
            ),
        ),
    );

    return div(
        { class: 'table-section' },
        div(
            {
                class: 'table-section-header',
                onclick: () => { open.val = !open.val; },
            },
            mat('table_rows', 22),
            span({ class: 'ts-name' }, tableName),
            span({ class: 'count-badge' }, `${rows.length} elem${rows.length !== 1 ? 's' : ''}`),
            pillsBar,
            span({ class: () => `table-section-chevron${open.val ? ' open' : ''}` }, 'expand_more'),
        ),
        () => open.val ? div({ class: 'matrix-table-wrap' }, matrixTable) : '',
    );
};
```

- [ ] **Step 3: Rewrite `CoverageMatrix`**

Replace the entire `CoverageMatrix` function with:

```javascript
const CoverageMatrix = (matrix, suiteScope, tables) => {
    if (!matrix.length) {
        return div({ class: 'dc-empty' }, 'No schema data available.');
    }

    // Group rows by table preserving order
    const tableMap = new Map();
    for (const row of matrix) {
        if (!tableMap.has(row.table)) tableMap.set(row.table, []);
        tableMap.get(row.table).push(row);
    }

    const scope = suiteScope || {};
    const scopeNote = scope.total > 0 && scope.excluded && scope.excluded.length > 0
        ? div(
            { class: 'matrix-scope-note' },
            mat('info', 13),
            ` Test counts reflect ${scope.included.length} of ${scope.total} suites — `,
            span({ style: 'opacity:0.7' }, scope.excluded.join(', ')),
            ' excluded.',
          )
        : '';

    // Build health-like object from matrix rows for the tier bars
    const tierHealth = { tg_enforced: 0, db_enforced: 0, unenforced: 0, uncovered: 0, n_elements: matrix.length };
    for (const row of matrix) {
        const t = row.tier || 'none';
        if (t === 'tg')   tierHealth.tg_enforced++;
        else if (t === 'db')  tierHealth.db_enforced++;
        else if (t === 'unf') tierHealth.unenforced++;
        else                  tierHealth.uncovered++;
    }

    // Active tier filter — clicking a bar row cross-filters the matrix
    const activeMatrixTier = van.state(null);

    const onTierClick = (tierKey) => {
        // map health key → data-tier value
        const keyMap = { tg_enforced: 'tg', db_enforced: 'db', unenforced: 'unf', uncovered: 'none' };
        const tier = keyMap[tierKey];
        activeMatrixTier.val = activeMatrixTier.val === tier ? null : tier;
    };

    const countsBar = (tables && tables.length) ? TermCountsBar(tables) : '';

    const tableEntries = [...tableMap.entries()];
    return div(
        { class: 'dc-matrix-wrap' },
        // ── Completeness bars at top ─────────────────────────────────────────
        div(
            { class: 'matrix-completeness' },
            div({ class: 'matrix-completeness__label' }, 'Contract Completeness'),
            div({ class: 'matrix-completeness__sub' }, `${tierHealth.n_elements} elements · click a row to filter`),
            () => {
                const activeTier = activeMatrixTier.val;
                // Pass a wrapped onTierClick that also dims inactive rows
                return CoverageTierBars(tierHealth, false, onTierClick);
            },
        ),
        div({ class: 'matrix-section-label' }, 'Coverage by table'),
        // ── Per-table accordions ──────────────────────────────────────────────
        () => {
            const activeTier = activeMatrixTier.val;
            return div(
                ...tableEntries.map(([tableName, rows], idx) => {
                    const filteredRows = activeTier
                        ? rows.map((r) => ({ ...r, _hidden: (r.tier || 'none') !== activeTier }))
                        : rows;
                    const totals = { db: 0, tested: 0, mon: 0, obs: 0, decl: 0 };
                    for (const r of rows) for (const c of MATRIX_COLS) totals[c.key] += r[c.key] || 0;
                    return MatrixTableSection(tableName, filteredRows, idx === 0, totals);
                }),
            );
        },
        countsBar,
        scopeNote,
    );
};
```

- [ ] **Step 4: Update `MatrixTableSection` to respect `_hidden` flag on rows**

In the rewritten `MatrixTableSection` above, the row `tr` render needs to respect `_hidden`. Update the rows map inside `matrixTable`:

```javascript
            ...rows.map((row) => tr(
                {
                    'data-tier': row.tier || 'none',
                    style: row._hidden ? 'display:none' : '',
                },
                // ... rest of cells unchanged
```

- [ ] **Step 5: Add CSS for new matrix elements**

In the stylesheet, after the `/* ── Coverage tier bars ── */` block added in Task 4, add:

```css
/* ── Matrix completeness header ── */
.matrix-completeness {
    background: var(--card-bg, #1e2130);
    border: 1px solid #2d3348;
    border-radius: 10px;
    padding: 14px 18px 14px;
    margin-bottom: 16px;
}
.matrix-completeness__label {
    font-size: 11px;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 4px;
}
.matrix-completeness__sub {
    font-size: 10px;
    color: #374151;
    margin-bottom: 12px;
}
.matrix-section-label {
    font-size: 10px;
    font-weight: 700;
    color: #374151;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 8px;
    padding-left: 2px;
}

/* ── Matrix tier pills in closed accordion header ── */
.matrix-pills-bar {
    display: flex;
    align-items: center;
    gap: 5px;
    flex: 1;
    justify-content: flex-end;
    margin-right: 8px;
    transition: opacity 0.12s;
}
.matrix-pills-bar--hidden {
    visibility: hidden;
}
.matrix-tier-pill {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    border-radius: 20px;
    font-size: 10px;
    font-weight: 600;
    background: rgba(255,255,255,0.05);
    color: var(--pill-color, #94a3b8);
    border: 1px solid rgba(255,255,255,0.08);
    white-space: nowrap;
}

/* ── Tier dot on column name ── */
.col-tier-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
    flex-shrink: 0;
}
.col-name--table {
    font-style: italic;
    color: #94a3b8;
    font-size: 11px;
    padding-left: 8px;
}

/* ── Matrix group column headers ── */
.group-th {
    text-align: center;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    padding: 8px 10px 4px;
    border-bottom: 1px solid #2d3348;
}
.group-th--tg  { border-left: 1px solid #2d3348; background: rgba(34,197,94,0.06); }
.group-th--db  { border-left: 1px solid #2d3348; background: rgba(129,140,248,0.06); }
.group-th--unf { border-left: 1px solid #2d3348; background: rgba(245,158,11,0.06); }
.group-th--unc { border-left: 1px solid #2d3348; color: #ef4444; width: 80px; }

.tier-col--tg  { background: rgba(34,197,94,0.04); }
.tier-col--db  { background: rgba(129,140,248,0.04); border-left: 1px solid #1e2536; }
.tier-col--unf { background: rgba(245,158,11,0.04); }
.tier-col--unc { background: rgba(239,68,68,0.03); border-left: 1px solid #1e2536; }

.tier-cell--tg  { background: rgba(34,197,94,0.04); }
.tier-cell--db  { background: rgba(129,140,248,0.04); border-left: 1px solid #1e2536; }
.tier-cell--unf { background: rgba(245,158,11,0.04); }
.tier-cell--unc { background: rgba(239,68,68,0.03); border-left: 1px solid #1e2536; text-align: center; }

/* Uncovered "Yes" pill */
.uncov-yes {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 700;
    background: rgba(239,68,68,0.18);
    color: #f87171;
    border: 1px solid rgba(239,68,68,0.35);
}
```

- [ ] **Step 6: Update the help footer text**

Find the help footer in `TermsHelpPanel` (around line 1092):

```javascript
        div(
            { class: 'help-footer' },
            span({ class: 'help-em' }, 'Contract Completeness'),
            ' measures what percentage of columns have at least one non-schema term ',
            '(classification, description, format pattern, or a quality test rule). ',
            'Columns with only DDL terms — and nothing richer — appear in the ',
            span({ class: 'help-em' }, 'Uncovered'),
            ' filter on the Overview tab.',
        ),
```

Replace with:

```javascript
        div(
            { class: 'help-footer' },
            span({ class: 'help-em' }, 'Contract Completeness'),
            ' classifies each column into the highest enforcement tier it reaches: ',
            span({ class: 'help-em' }, '⚡ TestGen Enforced'),
            ' (active test or monitor), ',
            span({ class: 'help-em' }, '🏛 DB Enforced'),
            ' (NOT NULL, PK, FK, or length/precision constraint), ',
            span({ class: 'help-em' }, '📋 Unenforced'),
            ' (declared or observed metadata only), or ',
            span({ class: 'help-em' }, '○ Uncovered'),
            ' (bare data type — nothing richer). Each element counts in exactly one tier.',
        ),
```

- [ ] **Step 7: Manual verification**

```bash
source venv/bin/activate && testgen run-app ui
```

Navigate to a data contract → Coverage Matrix tab. Verify:
- Completeness bars appear at the top of the matrix tab
- Each table accordion shows tier pills (⚡ N 🏛 N 📋 N ○ N) when collapsed, pills hidden when expanded
- Matrix columns are ordered: Tests | Monitors | DDL | Observed | Declared | Uncovered
- Columns with no tests/constraints/metadata show a red "Yes" in the Uncovered column
- Clicking a bar row in the completeness section dims non-matching rows

- [ ] **Step 8: Commit**

```bash
git add testgen/ui/components/frontend/js/pages/data_contract.js
git commit -m "feat: rewrite coverage matrix tab with tier model, completeness bars, and accordion pills"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|-----------------|-----------|
| `_classify_tier` replacing `_is_covered` | Task 1 |
| `_has_meaningful_ddl_constraint` | Task 1 |
| `_has_unenforced_terms` | Task 1 |
| Health dict: `tg_enforced`, `db_enforced`, `unenforced`, `uncovered`, `n_elements` | Task 2 |
| N = columns + table-level elements | Task 2, Task 3 |
| `tier` field on matrix rows | Task 3 |
| Table-level rows always in matrix (not just when tests exist) | Task 3 |
| HealthGrid: four stacked bars replace single bar | Task 4 |
| `CoverageTierBars` shared component | Task 4 |
| Coverage card still navigates to matrix tab | Task 4 (preserved `onclick`) |
| Completeness bars at top of matrix tab, always visible | Task 5 |
| Per-table pills in closed accordion header | Task 5 |
| Pills hidden when accordion open | Task 5 |
| Column order: TestGen → DB → Unenforced → Uncovered | Task 5 |
| Uncovered `Yes` pill only when tier == "none" | Task 5 |
| Cross-filter by clicking bar row | Task 5 |
| Help text updated | Task 5 |
| No changes to Terms Detail, YAML, Gap Analysis | Not touched |
| No new DB migrations | Confirmed — tier is computed at render time |

**Placeholder scan:** No TBDs, all code blocks present.

**Type consistency:** `_classify_enforcement_tier` defined in Task 1, imported in Task 1 (data_contract.py export), used in Task 2 (health dict) and Task 3 (matrix rows). `CoverageTierBars` defined and used in Task 4, reused in Task 5. `MATRIX_COLS` redefined in Task 5a and used in both `MatrixTableSection` (Task 5a) and `CoverageMatrix` (Task 5). `MATRIX_GROUPS` defined in Task 5a, used in `MatrixTableSection` group header row (Task 5a). `TIER_DOT_COLOR` defined in Task 5a, used in `MatrixTableSection` (Task 5a). All consistent.
