"""
Import an ODCS v3.1.0 data contract YAML document back into TestGen.

Round-trippable fields:
  - fundamentals: version, status, description.purpose, domain, dataProduct
  - quality:       per-test threshold, tolerance, description, active flag, custom_query (CUSTOM only)
  - slaProperties: latency → profiling_delay_days

Read-only fields (TestGen is the source of truth):
  - schema (column types, classification — driven by profiling)
  - servers (driven by connection config)
  - references (driven by Combo_Match test definitions)
  - compliance (driven by test results)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import yaml

from testgen.commands.export_data_contract import VALID_STATUSES
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import execute_db_queries, fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ContractDiff:
    """Describes what would change when applying an import."""
    contract_updates: dict[str, Any] = field(default_factory=dict)    # contract_version, contract_status, description → table_groups
    table_group_updates: dict[str, Any] = field(default_factory=dict)  # business_domain, data_product, profiling_delay_days → table_groups
    test_updates: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def total_changes(self) -> int:
        return len(self.contract_updates) + len(self.table_group_updates) + len(self.test_updates)

    def summary(self) -> str:
        parts = []
        if self.contract_updates:
            parts.append(f"{len(self.contract_updates)} contract field(s)")
        if self.table_group_updates:
            parts.append(f"{len(self.table_group_updates)} table group field(s)")
        if self.test_updates:
            parts.append(f"{len(self.test_updates)} test definition(s)")
        return ", ".join(parts) if parts else "no changes"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_contract_yaml(raw: str) -> tuple[dict | None, list[str]]:
    """Parse YAML and return (doc, errors). Validates minimum ODCS structure."""
    errors: list[str] = []
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, [f"YAML parse error: {exc}"]

    if not isinstance(doc, dict):
        return None, ["Document must be a YAML mapping."]

    if doc.get("apiVersion") != "v3.1.0":
        errors.append(f"Expected apiVersion 'v3.1.0', got '{doc.get('apiVersion')}'.")
    if doc.get("kind") != "DataContract":
        errors.append(f"Expected kind 'DataContract', got '{doc.get('kind')}'.")
    if not doc.get("id"):
        errors.append("Missing required field: id.")

    status = doc.get("status", "")
    if status and status not in VALID_STATUSES:
        errors.append(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}.")

    return doc, errors


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def compute_diff(doc: dict, table_group_id: str, schema: str) -> ContractDiff:
    """Compare imported document against current DB state and build a diff."""
    diff = ContractDiff()

    # --- fetch current state ---
    group_rows = fetch_dict_from_db(
        f"""
        SELECT id, table_groups_name, description,
               contract_version, contract_status,
               business_domain, data_product, profiling_delay_days
        FROM {schema}.table_groups
        WHERE id = :tg_id
        """,
        params={"tg_id": table_group_id},
    )
    if not group_rows:
        diff.errors.append(f"Table group '{table_group_id}' not found.")
        return diff

    current = dict(group_rows[0])

    # --- fundamentals ---
    if doc.get("version") and doc["version"] != current.get("contract_version"):
        diff.contract_updates["contract_version"] = doc["version"]

    imported_status = (doc.get("status") or "").lower()
    if imported_status and imported_status != current.get("contract_status"):
        diff.contract_updates["contract_status"] = imported_status

    purpose = (doc.get("description") or {}).get("purpose") if isinstance(doc.get("description"), dict) else None
    if purpose and purpose != current.get("description"):
        diff.contract_updates["description"] = purpose

    if doc.get("domain") and doc["domain"] != current.get("business_domain"):
        diff.table_group_updates["business_domain"] = doc["domain"]

    if doc.get("dataProduct") and doc["dataProduct"] != current.get("data_product"):
        diff.table_group_updates["data_product"] = doc["dataProduct"]

    # --- slaProperties → profiling_delay_days ---
    for sla in doc.get("slaProperties") or []:
        if sla.get("property") == "latency" and sla.get("unit") in ("day", "d"):
            try:
                new_delay = int(sla["value"])
                if new_delay != current.get("profiling_delay_days"):
                    diff.table_group_updates["profiling_delay_days"] = new_delay
            except (TypeError, ValueError):
                diff.warnings.append(f"Could not parse latency SLA value: {sla.get('value')}")

    # --- quality → test_definitions ---
    if doc.get("quality"):
        test_rows = fetch_dict_from_db(
            f"""
            SELECT td.id, td.test_type, td.test_description, td.test_active,
                   td.threshold_value, td.lower_tolerance, td.upper_tolerance,
                   td.custom_query, td.skip_errors, td.severity
            FROM {schema}.test_definitions td
            JOIN {schema}.test_suites s ON s.id = td.test_suite_id
            WHERE s.table_groups_id = :tg_id
              AND s.include_in_contract IS NOT FALSE  -- TRUE or NULL; column is NOT NULL DEFAULT TRUE so NULL only on pre-migration rows
              AND td.test_active = 'Y'
            """,
            params={"tg_id": table_group_id},
        )
        current_tests = {str(r["id"]): dict(r) for r in test_rows}

        for rule in doc["quality"]:
            rule_id = rule.get("id")
            if not rule_id or rule_id not in current_tests:
                if rule_id:
                    diff.warnings.append(f"Quality rule id '{rule_id}' not found in test suite — skipped.")
                continue

            current_test = current_tests[rule_id]
            updates: dict[str, Any] = {"id": rule_id}

            # description
            imported_name = rule.get("name")
            if imported_name and imported_name != current_test.get("test_description"):
                updates["test_description"] = imported_name

            # threshold (operator key holds the value)
            for op_key in ("mustBe", "mustBeGreaterThan", "mustBeGreaterOrEqualTo",
                           "mustBeLessThan", "mustBeLessOrEqualTo"):
                if op_key in rule:
                    new_val = str(rule[op_key])
                    if new_val != current_test.get("threshold_value"):
                        updates["threshold_value"] = new_val
                    break

            # tolerance band
            if "mustBeBetween" in rule and isinstance(rule["mustBeBetween"], list) and len(rule["mustBeBetween"]) == 2:
                lo, hi = str(rule["mustBeBetween"][0]), str(rule["mustBeBetween"][1])
                if lo != current_test.get("lower_tolerance"):
                    updates["lower_tolerance"] = lo
                if hi != current_test.get("upper_tolerance"):
                    updates["upper_tolerance"] = hi

            # severity
            if rule.get("severity") and rule["severity"] != current_test.get("severity"):
                updates["severity"] = rule["severity"]

            # custom_query (CUSTOM tests only)
            if current_test["test_type"] == "CUSTOM" and rule.get("query"):
                if rule["query"] != current_test.get("custom_query"):
                    updates["custom_query"] = rule["query"]

            # skip_errors (CUSTOM tests only)
            if current_test["test_type"] == "CUSTOM" and "mustBeLessOrEqualTo" in rule:
                try:
                    new_skip = int(rule["mustBeLessOrEqualTo"])
                    if new_skip != current_test.get("skip_errors"):
                        updates["skip_errors"] = new_skip
                except (TypeError, ValueError):
                    pass

            if len(updates) > 1:  # more than just the id key
                diff.test_updates.append(updates)

    return diff


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

# Whitelists prevent unexpected columns from being injected via the diff object.
_ALLOWED_GROUP_COLS: frozenset[str] = frozenset({
    "contract_version", "contract_status", "description",
    "business_domain", "data_product", "profiling_delay_days",
})
_ALLOWED_TEST_COLS: frozenset[str] = frozenset({
    "test_description", "threshold_value", "lower_tolerance",
    "upper_tolerance", "severity", "custom_query", "skip_errors",
})


def apply_diff(diff: ContractDiff, table_group_id: str, schema: str) -> None:
    """Write the diff to the database. Caller must ensure no errors in diff."""
    if diff.has_errors:
        raise ValueError(f"Cannot apply diff with errors: {diff.errors}")

    db_queries: list[tuple[str, dict]] = []

    # contract_updates and table_group_updates both target the table_groups table.
    all_group_updates = {**diff.contract_updates, **diff.table_group_updates}
    if all_group_updates:
        invalid = set(all_group_updates) - _ALLOWED_GROUP_COLS
        if invalid:
            raise ValueError(f"Unexpected table_groups columns in diff: {invalid}")
        params: dict[str, Any] = {"tg_id": table_group_id}
        set_parts = []
        for col, val in all_group_updates.items():
            param_name = f"p_{col}"
            set_parts.append(f"{col} = :{param_name}")
            params[param_name] = val
        db_queries.append((
            f"UPDATE {schema}.table_groups SET {', '.join(set_parts)} WHERE id = :tg_id",
            params,
        ))

    for test_update in diff.test_updates:
        test_update = dict(test_update)  # don't mutate caller's list
        test_id = test_update.pop("id")
        if not test_update:
            continue
        invalid = set(test_update) - _ALLOWED_TEST_COLS
        if invalid:
            raise ValueError(f"Unexpected test_definitions columns in diff: {invalid}")
        params = {"test_id": test_id, "lock_y": "Y"}
        set_parts = []
        for col, val in test_update.items():
            param_name = f"p_{col}"
            set_parts.append(f"{col} = :{param_name}")
            params[param_name] = val
        db_queries.append((
            f"UPDATE {schema}.test_definitions SET {', '.join(set_parts)}, "
            f"last_manual_update = NOW(), lock_refresh = :lock_y "
            f"WHERE id = :test_id",
            params,
        ))

    if db_queries:
        execute_db_queries(db_queries)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@with_database_session
def run_import_data_contract(yaml_content: str, table_group_id: str, dry_run: bool = False) -> ContractDiff:
    """
    Parse a YAML contract and apply it to the given table group.

    Args:
        yaml_content: Raw YAML string of the ODCS document.
        table_group_id: UUID of the target table group.
        dry_run: If True, compute and return the diff without writing to DB.

    Returns:
        ContractDiff describing what was (or would be) changed.
    """
    schema = get_tg_schema()

    doc, errors = validate_contract_yaml(yaml_content)
    if errors or doc is None:
        diff = ContractDiff()
        diff.errors.extend(errors or ["Failed to parse YAML document."])
        return diff

    diff = compute_diff(doc, table_group_id, schema)

    # Warn if the target group has suites but none are marked for contract inclusion
    if not diff.has_errors:
        suite_rows = fetch_dict_from_db(
            f"SELECT COUNT(*) AS total, SUM(CASE WHEN include_in_contract IS NOT FALSE THEN 1 ELSE 0 END) AS included"
            f" FROM {schema}.test_suites WHERE table_groups_id = :tg_id AND is_monitor IS NOT TRUE",
            params={"tg_id": table_group_id},
        )
        if suite_rows:
            sr = dict(suite_rows[0])
            if int(sr.get("total") or 0) > 0 and int(sr.get("included") or 0) == 0:
                diff.warnings.append(
                    "No test suites are marked 'Include in Data Contract' for this table group — "
                    "quality rule changes in the contract will have no effect."
                )

    if not dry_run and not diff.has_errors and diff.total_changes > 0:
        apply_diff(diff, table_group_id, schema)
        LOG.info("Data contract imported: %s changes applied to table group %s", diff.total_changes, table_group_id)
    elif diff.total_changes == 0 and not diff.has_errors:
        LOG.info("Data contract import: no changes detected for table group %s", table_group_id)

    return diff
