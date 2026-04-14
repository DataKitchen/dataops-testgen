"""
Staleness diff — compare a saved contract YAML snapshot against current DB state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

from testgen.commands.export_data_contract import _pii_flag_to_classification
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")

_TYPE_ALIASES: dict[str, str] = {
    "character varying": "varchar",
    "character":         "char",
    "integer":           "int",
    "int4":              "int",
    "int8":              "bigint",
    "int2":              "smallint",
    "float4":            "real",
    "float8":            "double precision",
    "bool":              "boolean",
    "timestamptz":       "timestamp with time zone",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StaleDiff:
    schema_changes: list[dict[str, Any]] = field(default_factory=list)
    # each: {"change": "added"|"removed"|"changed", "table": str, "column": str, "detail": str}

    quality_changes: list[dict[str, Any]] = field(default_factory=list)
    # each: {"change": "added"|"removed"|"changed", "element": str, "test_type": str,
    #        "detail": str, "last_result": str | None}

    governance_changes: list[dict[str, Any]] = field(default_factory=list)
    # each: {"change": "changed", "table": str, "column": str, "field": str, "detail": str}

    suite_scope_changes: list[dict[str, Any]] = field(default_factory=list)
    # each: {"change": "added"|"removed", "suite_name": str}

    @property
    def is_empty(self) -> bool:
        return not any([self.schema_changes, self.quality_changes,
                        self.governance_changes, self.suite_scope_changes])

    def summary_parts(self) -> list[str]:
        """Human-readable summary strings, e.g. ['2 new columns', '1 test changed']"""
        parts = []
        added_cols = sum(1 for c in self.schema_changes if c["change"] == "added")
        removed_cols = sum(1 for c in self.schema_changes if c["change"] == "removed")
        changed_cols = sum(1 for c in self.schema_changes if c["change"] == "changed")
        if added_cols:
            parts.append(f"{added_cols} new column{'s' if added_cols != 1 else ''} detected")
        if removed_cols:
            parts.append(f"{removed_cols} column{'s' if removed_cols != 1 else ''} removed")
        if changed_cols:
            parts.append(f"{changed_cols} column type{'s' if changed_cols != 1 else ''} changed")

        added_tests = sum(1 for c in self.quality_changes if c["change"] == "added")
        removed_tests = sum(1 for c in self.quality_changes if c["change"] == "removed")
        changed_tests = sum(1 for c in self.quality_changes if c["change"] == "changed")
        if added_tests:
            parts.append(f"{added_tests} new test{'s' if added_tests != 1 else ''} added")
        if removed_tests:
            parts.append(f"{removed_tests} test{'s' if removed_tests != 1 else ''} removed")
        if changed_tests:
            parts.append(f"{changed_tests} test threshold{'s' if changed_tests != 1 else ''} changed")

        if self.governance_changes:
            n = len(self.governance_changes)
            parts.append(f"{n} governance field{'s' if n != 1 else ''} changed")

        added_suites = sum(1 for c in self.suite_scope_changes if c["change"] == "added")
        removed_suites = sum(1 for c in self.suite_scope_changes if c["change"] == "removed")
        if added_suites:
            parts.append(f"{added_suites} suite{'s' if added_suites != 1 else ''} added to contract")
        if removed_suites:
            parts.append(f"{removed_suites} suite{'s' if removed_suites != 1 else ''} removed from contract")

        return parts


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
    last_result: str | None  # "passed"/"failed"/"warning"/"error"/None (None = not run)
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


# ---------------------------------------------------------------------------
# Shared threshold helpers (used by both compute_term_diff and compute_staleness_diff)
# ---------------------------------------------------------------------------

def _snap_threshold_from_rule(rule: dict[str, Any]) -> str | None:
    """Extract the threshold string from an ODCS quality rule dict.

    Returns ``"low,high"`` for ``mustBeBetween`` ranges, a plain string for single-value
    operators, or ``None`` if the rule has no threshold key.
    """
    for op in ("mustBe", "mustBeGreaterThan", "mustBeGreaterOrEqualTo",
               "mustBeLessThan", "mustBeLessOrEqualTo"):
        if op in rule:
            return str(rule[op])
    if "mustBeBetween" in rule:
        between = rule["mustBeBetween"]
        if isinstance(between, list) and len(between) == 2:
            return f"{between[0]},{between[1]}"
    return None


def _cur_threshold_from_row(row: dict[str, Any]) -> str:
    """Build the DB-side threshold string using the same logic as the YAML export.

    If both ``lower_tolerance`` and ``upper_tolerance`` are set the export writes
    ``mustBeBetween: [lower, upper]``, which ``_snap_threshold_from_rule`` returns as
    ``"lower,upper"``.  Match that format here so the comparison is apples-to-apples.
    """
    lower = row.get("lower_tolerance")
    upper = row.get("upper_tolerance")
    if lower is not None and upper is not None:
        return f"{lower},{upper}"
    val = row.get("threshold_value")
    return str(val) if val is not None else ""


def _thresholds_differ(snap: str, cur: str) -> bool:
    """Compare thresholds numerically when possible to avoid float/string mismatches.

    Handles:
    - Single value: ``"1000"`` vs ``"1000.0"`` → equal
    - Range (comma-separated): ``"10,90"`` vs ``"10.0,90.0"`` → equal
    - Non-numeric (e.g. regex patterns): falls back to string comparison
    """
    if snap == cur:
        return False
    snap_parts = snap.split(",")
    cur_parts  = cur.split(",")
    # If one side is a range and the other is a single value, they differ by definition
    if len(snap_parts) != len(cur_parts):
        return True
    if len(snap_parts) == 2 and len(cur_parts) == 2:
        try:
            return (float(snap_parts[0]) != float(cur_parts[0])
                    or float(snap_parts[1]) != float(cur_parts[1]))
        except (ValueError, TypeError):
            return snap != cur
    try:
        return float(snap) != float(cur)
    except (ValueError, TypeError):
        return snap != cur


# ---------------------------------------------------------------------------
# Term diff helpers and main function
# ---------------------------------------------------------------------------

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
    snapshot_suite_id: str | None = None,
) -> TermDiffResult:
    """
    Compare the saved contract YAML snapshot against the current active test definitions
    and return a TermDiffResult with per-term diff entries and compliance status counts.

    When *snapshot_suite_id* is provided the query is scoped exclusively to that suite,
    which is the authoritative source of truth for a versioned contract snapshot.

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
    # 2. Query current test definitions.
    # When snapshot_suite_id is set, scope exclusively to that suite.
    # Otherwise, query across all source suites (monitors excluded — monitor
    # tests are regenerated with new IDs on each monitor run, so including
    # them would produce spurious "deleted"/"new" counts in the thousands).
    # ------------------------------------------------------------------
    if snapshot_suite_id:
        test_rows = fetch_dict_from_db(
            f"""
            SELECT COALESCE(td.source_test_definition_id, td.id)::text AS id,
                   td.test_type,
                   td.table_name,
                   td.column_name,
                   td.threshold_value,
                   td.lower_tolerance,
                   td.upper_tolerance,
                   CASE tr.result_status
                       WHEN 'Passed'  THEN 'passed'
                       WHEN 'Failed'  THEN 'failed'
                       WHEN 'Warning' THEN 'warning'
                       WHEN 'Error'   THEN 'error'
                       ELSE NULL
                   END AS last_status
            FROM {schema}.test_definitions td
            JOIN {schema}.test_types  tt ON tt.test_type = td.test_type
            LEFT JOIN LATERAL (
                SELECT result_status FROM {schema}.test_results
                WHERE  test_definition_id = td.id
                ORDER  BY test_time DESC LIMIT 1
            ) tr ON TRUE
            WHERE td.test_suite_id             = CAST(:snapshot_suite_id AS uuid)
              AND td.test_active               = 'Y'
              AND COALESCE(tt.test_scope, '') != 'referential'
            """,
            params={"snapshot_suite_id": snapshot_suite_id},
        )
    else:
        test_rows = fetch_dict_from_db(
            f"""
            SELECT td.id::text AS id,
                   td.test_type,
                   td.table_name,
                   td.column_name,
                   td.threshold_value,
                   td.lower_tolerance,
                   td.upper_tolerance,
                   CASE tr.result_status
                       WHEN 'Passed'  THEN 'passed'
                       WHEN 'Failed'  THEN 'failed'
                       WHEN 'Warning' THEN 'warning'
                       WHEN 'Error'   THEN 'error'
                       ELSE NULL
                   END AS last_status
            FROM {schema}.test_definitions td
            JOIN {schema}.test_suites ts ON ts.id = td.test_suite_id
            JOIN {schema}.test_types  tt ON tt.test_type = td.test_type
            LEFT JOIN LATERAL (
                SELECT result_status FROM {schema}.test_results
                WHERE  test_definition_id = td.id
                ORDER  BY test_time DESC LIMIT 1
            ) tr ON TRUE
            WHERE ts.table_groups_id         = :tg_id
              AND ts.include_in_contract     IS NOT FALSE
              AND COALESCE(ts.is_contract_snapshot, FALSE) = FALSE
              AND COALESCE(ts.is_monitor, FALSE) = FALSE
              AND td.test_active             = 'Y'
              AND COALESCE(tt.test_scope, '') != 'referential'
            """,
            params={"tg_id": table_group_id},
        )
    current_tests: dict[str, dict[str, Any]] = {str(r["id"]): dict(r) for r in test_rows}
    result.current_count = len(current_tests)

    def _element_of(row: dict[str, Any]) -> str:
        col = (row.get("column_name") or "").strip()
        tbl = (row.get("table_name")  or "").strip()
        return f"{tbl}.{col}" if col else tbl

    # Use module-level threshold helpers (shared with compute_staleness_diff)

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
            snap_thresh = _snap_threshold_from_rule(rule)
            cur_thresh  = _cur_threshold_from_row(row)

            if snap_thresh is not None and _thresholds_differ(snap_thresh, cur_thresh):
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


# ---------------------------------------------------------------------------
# Main diff function
# ---------------------------------------------------------------------------

@with_database_session
def compute_staleness_diff(
    table_group_id: str,
    saved_yaml: str,
    snapshot_suite_id: str | None = None,
) -> StaleDiff:
    """
    Compare a saved ODCS contract YAML snapshot against the current database state
    and return a StaleDiff describing what has changed.

    Args:
        table_group_id: UUID of the table group.
        saved_yaml: Raw YAML string of the previously saved contract snapshot.

    Returns:
        A StaleDiff instance; empty (is_empty=True) when nothing has changed.
    """
    diff = StaleDiff()
    schema = get_tg_schema()

    # ------------------------------------------------------------------
    # 1. Parse the saved YAML snapshot
    # ------------------------------------------------------------------
    try:
        snapshot: dict[str, Any] = yaml.safe_load(saved_yaml) or {}
    except yaml.YAMLError as exc:
        LOG.warning("Failed to parse saved contract YAML for staleness diff: %s", exc)
        return diff

    if not isinstance(snapshot, dict):
        LOG.warning("Saved contract YAML is not a mapping; skipping staleness diff.")
        return diff

    # ------------------------------------------------------------------
    # 2. Schema diff
    # ------------------------------------------------------------------

    # Build snapshot column index: "table.column" → {"physical_type": str}
    snapshot_cols: dict[str, dict[str, Any]] = {}
    for table_entry in snapshot.get("schema") or []:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name") or ""
        for prop in table_entry.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            col_name = prop.get("name") or ""
            key = f"{table_name}.{col_name}"
            snapshot_cols[key] = {"physical_type": prop.get("physicalType") or ""}

    # Query current columns from DB
    col_rows = fetch_dict_from_db(
        f"""
        SELECT table_name, column_name, general_type, db_data_type
        FROM {schema}.data_column_chars
        WHERE table_groups_id = :tg_id
        ORDER BY table_name, ordinal_position
        """,
        params={"tg_id": table_group_id},
    )
    current_cols: dict[str, dict[str, Any]] = {
        f"{r['table_name']}.{r['column_name']}": {
            "physical_type": r.get("db_data_type") or "",
            "table_name": r["table_name"],
            "column_name": r["column_name"],
        }
        for r in col_rows
    }

    # Added columns (in DB but not in snapshot)
    for key, cur in current_cols.items():
        if key not in snapshot_cols:
            diff.schema_changes.append({
                "change": "added",
                "table":  cur["table_name"],
                "column": cur["column_name"],
                "detail": f"New column detected (type: {cur['physical_type'] or 'unknown'})",
            })

    # Removed columns (in snapshot but not in DB)
    for key in snapshot_cols:
        if key not in current_cols:
            parts = key.split(".", 1)
            table_name, col_name = (parts[0], parts[1]) if len(parts) == 2 else (key, "")
            diff.schema_changes.append({
                "change": "removed",
                "table":  table_name,
                "column": col_name,
                "detail": "Column no longer present in profiled data",
            })

    def _norm_type(t: str) -> str:
        return _TYPE_ALIASES.get(t.lower().strip(), t.lower().strip())

    # Changed columns (data_type differs)
    for key in snapshot_cols:
        if key in current_cols:
            snap_type = snapshot_cols[key]["physical_type"]
            curr_type = current_cols[key]["physical_type"]
            if snap_type and curr_type and _norm_type(snap_type) != _norm_type(curr_type):
                cur = current_cols[key]
                diff.schema_changes.append({
                    "change": "changed",
                    "table":  cur["table_name"],
                    "column": cur["column_name"],
                    "detail": f"Type changed from '{snap_type}' to '{curr_type}'",
                })

    # ------------------------------------------------------------------
    # 3. Quality (test definitions) diff
    # ------------------------------------------------------------------

    if not snapshot_suite_id:
        # Build snapshot quality index: rule_id → rule dict
        snapshot_quality: dict[str, dict[str, Any]] = {}
        for rule in snapshot.get("quality") or []:
            if not isinstance(rule, dict):
                continue
            rule_id = rule.get("id")
            if rule_id:
                snapshot_quality[str(rule_id)] = rule

        # Query current active test definitions with last result (exclude referential — not in quality YAML)
        test_rows = fetch_dict_from_db(
            f"""
            SELECT td.id::text, td.test_type, td.table_name, td.column_name,
                   td.threshold_value, td.lower_tolerance, td.upper_tolerance,
                   td.test_description,
                   tr.result_status AS last_result_status
            FROM {schema}.test_definitions td
            JOIN {schema}.test_suites ts ON ts.id = td.test_suite_id
            JOIN {schema}.test_types  tt ON tt.test_type = td.test_type
            LEFT JOIN LATERAL (
                SELECT result_status FROM {schema}.test_results
                WHERE test_definition_id = td.id
                ORDER BY test_time DESC LIMIT 1
            ) tr ON TRUE
            WHERE ts.table_groups_id = :tg_id
              AND ts.include_in_contract IS NOT FALSE
              AND ts.is_monitor IS NOT TRUE
              AND COALESCE(ts.is_contract_snapshot, FALSE) = FALSE
              AND td.test_active = 'Y'
              AND COALESCE(tt.test_scope, '') != 'referential'
            """,
            params={"tg_id": table_group_id},
        )
        current_tests: dict[str, dict[str, Any]] = {str(r["id"]): dict(r) for r in test_rows}

        def _element_label(row: dict[str, Any]) -> str:
            col = (row.get("column_name") or "").strip()
            tbl = (row.get("table_name") or "").strip()
            return f"{tbl}.{col}" if col else tbl

        # Added tests (in DB but not in snapshot)
        for test_id, row in current_tests.items():
            if test_id not in snapshot_quality:
                diff.quality_changes.append({
                    "change":      "added",
                    "element":     _element_label(row),
                    "test_type":   row.get("test_type") or "",
                    "detail":      "New test definition added",
                    "last_result": row.get("last_result_status"),
                })

        # Removed tests (in snapshot but not in DB)
        for rule_id, rule in snapshot_quality.items():
            if rule_id not in current_tests:
                element = rule.get("element") or ""
                diff.quality_changes.append({
                    "change":      "removed",
                    "element":     element,
                    "test_type":   "",
                    "detail":      "Test definition removed or deactivated",
                    "last_result": None,
                })

        # Changed tests (threshold value differs)
        for rule_id, rule in snapshot_quality.items():
            if rule_id not in current_tests:
                continue
            row = current_tests[rule_id]
            snap_threshold    = _snap_threshold_from_rule(rule)
            current_threshold = _cur_threshold_from_row(row)

            if snap_threshold is not None and _thresholds_differ(snap_threshold, current_threshold):
                diff.quality_changes.append({
                    "change":      "changed",
                    "element":     _element_label(row),
                    "test_type":   row.get("test_type") or "",
                    "detail":      f"Threshold changed from '{snap_threshold}' to '{current_threshold}'",
                    "last_result": row.get("last_result_status"),
                })

    # ------------------------------------------------------------------
    # 4. Governance diff
    # ------------------------------------------------------------------

    # Build snapshot governance from schema properties
    # Keys: "table.column" → {"classification": str, "cde": bool, "description": str}
    snapshot_gov: dict[str, dict[str, Any]] = {}
    for table_entry in snapshot.get("schema") or []:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name") or ""
        for prop in table_entry.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            col_name = prop.get("name") or ""
            key = f"{table_name}.{col_name}"
            snapshot_gov[key] = {
                "classification": prop.get("classification") or "public",
                "cde":            bool(prop.get("criticalDataElement", False)),
                "description":    prop.get("description") or "",
            }

    # Query current governance state
    gov_rows = fetch_dict_from_db(
        f"""
        SELECT table_name, column_name, pii_flag, critical_data_element, description
        FROM {schema}.data_column_chars
        WHERE table_groups_id = :tg_id
        """,
        params={"tg_id": table_group_id},
    )

    for gov_row in gov_rows:
        table_name = gov_row["table_name"]
        col_name = gov_row["column_name"]
        key = f"{table_name}.{col_name}"

        if key not in snapshot_gov:
            continue  # new column — already captured in schema_changes

        snap = snapshot_gov[key]
        current_classification = _pii_flag_to_classification(gov_row.get("pii_flag"))
        current_cde = bool(gov_row.get("critical_data_element"))
        current_description = gov_row.get("description") or ""

        if snap["classification"] != current_classification:
            diff.governance_changes.append({
                "change": "changed",
                "table":  table_name,
                "column": col_name,
                "field":  "classification",
                "detail": f"'{snap['classification']}' → '{current_classification}'",
            })

        if snap["cde"] != current_cde:
            diff.governance_changes.append({
                "change": "changed",
                "table":  table_name,
                "column": col_name,
                "field":  "criticalDataElement",
                "detail": f"{snap['cde']} → {current_cde}",
            })

        if snap["description"] != current_description:
            diff.governance_changes.append({
                "change": "changed",
                "table":  table_name,
                "column": col_name,
                "field":  "description",
                "detail": "Description text changed",
            })

    # ------------------------------------------------------------------
    # 5. Suite scope diff
    # ------------------------------------------------------------------

    snapshot_suites: set[str] = set(
        (snapshot.get("x-testgen") or {}).get("includedSuites") or []
    )

    suite_rows = fetch_dict_from_db(
        f"""
        SELECT test_suite AS suite_name FROM {schema}.test_suites
        WHERE table_groups_id = :tg_id
          AND include_in_contract IS NOT FALSE
          AND is_monitor IS NOT TRUE
          AND is_contract_snapshot IS NOT TRUE
        """,
        params={"tg_id": table_group_id},
    )
    current_suites: set[str] = {r["suite_name"] for r in suite_rows}

    for suite_name in sorted(current_suites - snapshot_suites):
        diff.suite_scope_changes.append({"change": "added", "suite_name": suite_name})

    for suite_name in sorted(snapshot_suites - current_suites):
        diff.suite_scope_changes.append({"change": "removed", "suite_name": suite_name})

    return diff
