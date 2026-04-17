"""
Term diff — compare a saved contract YAML snapshot against current DB state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import yaml

from testgen.commands.export_data_contract import _pii_flag_to_classification
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class TermStatus(StrEnum):
    SAME    = "same"
    CHANGED = "changed"
    NEW     = "new"
    DELETED = "deleted"


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
# Shared threshold helpers
# ---------------------------------------------------------------------------

def _snap_threshold_from_rule(rule: dict[str, Any]) -> str | None:
    """Extract the threshold string from an ODCS quality rule dict."""
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
    """Build the DB-side threshold string to match _snap_threshold_from_rule format."""
    lower = row.get("lower_tolerance")
    upper = row.get("upper_tolerance")
    if lower is not None and upper is not None:
        return f"{lower},{upper}"
    val = row.get("threshold_value")
    return str(val) if val is not None else ""


def _thresholds_differ(snap: str, cur: str) -> bool:
    """Compare thresholds numerically when possible to avoid float/string mismatches."""
    if snap == cur:
        return False
    snap_parts = snap.split(",")
    cur_parts  = cur.split(",")
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

def _element_str(row: dict[str, Any]) -> str:
    """Return 'table.column' or just 'table' from a test-definition row."""
    col = (row.get("column_name") or "").strip()
    tbl = (row.get("table_name") or "").strip()
    return f"{tbl}.{col}" if col else tbl


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

    When *snapshot_suite_id* is provided the query is scoped exclusively to that suite.
    """
    result = TermDiffResult()
    schema = get_tg_schema()

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
              AND COALESCE(ts.is_contract_suite, FALSE) = FALSE
              AND td.test_active             = 'Y'
              AND COALESCE(tt.test_scope, '') != 'referential'
            """,
            params={"tg_id": table_group_id},
        )
        monitor_rows = fetch_dict_from_db(
            f"""
            SELECT CASE tr.result_status
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
              AND COALESCE(ts.is_monitor, FALSE) = TRUE
              AND td.test_active             = 'Y'
              AND COALESCE(tt.test_scope, '') != 'referential'
            """,
            params={"tg_id": table_group_id},
        )
        for mrow in monitor_rows:
            _add_status_count(result, True, mrow.get("last_status"))

    current_tests: dict[str, dict[str, Any]] = {str(r["id"]): dict(r) for r in test_rows}
    result.current_count = len(current_tests)

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
                    element=element or _element_str(row),
                    test_type=row.get("test_type") or "",
                    status=TermStatus.CHANGED,
                    detail=f"threshold: {snap_thresh} → {cur_thresh}",
                    last_result=last_result,
                    is_monitor=is_monitor,
                )
            else:
                entry = TermDiffEntry(
                    element=element or _element_str(row),
                    test_type=row.get("test_type") or "",
                    status=TermStatus.SAME,
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
                status=TermStatus.DELETED,
                detail=None,
                last_result=None,
                is_monitor=False,
            ))

    for test_id, row in current_tests.items():
        if test_id not in saved_quality:
            result.entries.append(TermDiffEntry(
                element=_element_str(row),
                test_type=row.get("test_type") or "",
                status=TermStatus.NEW,
                detail=None,
                last_result=row.get("last_status"),
                is_monitor=bool(row.get("is_monitor", False)),
            ))

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
