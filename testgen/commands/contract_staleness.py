"""
Staleness diff — compare a saved contract YAML snapshot against current DB state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")


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
# Helpers
# ---------------------------------------------------------------------------

def _pii_flag_to_classification(pii_flag: str | None) -> str:
    """Map a TestGen pii_flag value to an ODCS classification string."""
    if not pii_flag:
        return "public"
    if pii_flag.startswith("A/"):
        return "confidential"
    return "restricted"


# ---------------------------------------------------------------------------
# Main diff function
# ---------------------------------------------------------------------------

@with_database_session
def compute_staleness_diff(table_group_id: str, saved_yaml: str) -> StaleDiff:
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
        SELECT table_name, column_name, general_type, data_type
        FROM {schema}.data_column_chars
        WHERE table_groups_id = :tg_id
        ORDER BY table_name, ordinal_position
        """,
        params={"tg_id": table_group_id},
    )
    current_cols: dict[str, dict[str, Any]] = {
        f"{r['table_name']}.{r['column_name']}": {
            "physical_type": r.get("data_type") or "",
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

    # Changed columns (data_type differs)
    for key in snapshot_cols:
        if key in current_cols:
            snap_type = snapshot_cols[key]["physical_type"]
            curr_type = current_cols[key]["physical_type"]
            if snap_type and curr_type and snap_type.lower() != curr_type.lower():
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

    # Build snapshot quality index: rule_id → rule dict
    snapshot_quality: dict[str, dict[str, Any]] = {}
    for rule in snapshot.get("quality") or []:
        if not isinstance(rule, dict):
            continue
        rule_id = rule.get("id")
        if rule_id:
            snapshot_quality[str(rule_id)] = rule

    # Query current active test definitions with last result
    test_rows = fetch_dict_from_db(
        f"""
        SELECT td.id::text, td.test_type, td.table_name, td.column_name,
               td.threshold_value, td.test_description,
               tr.status AS last_result_status
        FROM {schema}.test_definitions td
        JOIN {schema}.test_suites ts ON ts.id = td.test_suite_id
        LEFT JOIN LATERAL (
            SELECT status FROM {schema}.test_results
            WHERE test_definition_id_fk = td.id
            ORDER BY test_time DESC LIMIT 1
        ) tr ON TRUE
        WHERE ts.table_groups_id = :tg_id
          AND ts.include_in_contract IS NOT FALSE
          AND ts.is_monitor IS NOT TRUE
          AND td.test_active = 'Y'
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
        current_threshold = str(row.get("threshold_value") or "")

        snap_threshold: str | None = None
        for op_key in ("mustBe", "mustBeGreaterThan", "mustBeGreaterOrEqualTo",
                       "mustBeLessThan", "mustBeLessOrEqualTo"):
            if op_key in rule:
                snap_threshold = str(rule[op_key])
                break
        if snap_threshold is None and "mustBeBetween" in rule:
            between = rule["mustBeBetween"]
            if isinstance(between, list) and len(between) == 2:
                snap_threshold = f"{between[0]},{between[1]}"

        if snap_threshold is not None and snap_threshold != current_threshold:
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
        SELECT suite_name FROM {schema}.test_suites
        WHERE table_groups_id = :tg_id
          AND include_in_contract IS NOT FALSE
          AND is_monitor IS NOT TRUE
        """,
        params={"tg_id": table_group_id},
    )
    current_suites: set[str] = {r["suite_name"] for r in suite_rows}

    for suite_name in sorted(current_suites - snapshot_suites):
        diff.suite_scope_changes.append({"change": "added", "suite_name": suite_name})

    for suite_name in sorted(snapshot_suites - current_suites):
        diff.suite_scope_changes.append({"change": "removed", "suite_name": suite_name})

    return diff
