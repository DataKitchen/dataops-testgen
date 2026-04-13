"""
ODCS v3.1.0 ↔ TestGen round-trip import/export.

Supports:
  CREATE  – new TestGen tests from YAML rules without an ``id`` field
  UPDATE  – existing tests from YAML rules with an ``id`` (threshold, severity, description)
  WRITE-BACK – new test UUIDs are written back into the source YAML file after creates

Unsupported (WARN + skip):
  - metric: missingValues       – no TestGen equivalent
  - operator: mustNotBe / mustNotBeBetween
  - type: custom  engine ≠ testgen
  - invalidValues without arguments.validValues or arguments.pattern
  - rowCount with unit: percent
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

from testgen.commands.export_data_contract import VALID_STATUSES
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import execute_db_queries, fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ODCS operators that carry a scalar threshold
_SCALAR_OPERATORS: tuple[str, ...] = (
    "mustBe",
    "mustBeGreaterThan",
    "mustBeGreaterOrEqualTo",
    "mustBeLessThan",
    "mustBeLessOrEqualTo",
)

# Scalar ODCS operator → TestGen test_operator string
_OPERATOR_TO_DB: dict[str, str] = {
    "mustBe":                  "=",
    "mustBeGreaterThan":       ">",
    "mustBeGreaterOrEqualTo":  ">=",
    "mustBeLessThan":          "<",
    "mustBeLessOrEqualTo":     "<=",
}

# (metric, unit) → TestGen test_type for unambiguous cases
_METRIC_UNIT_TO_TYPE: dict[tuple[str, str], str] = {
    ("nullValues",      "percent"): "Missing_Pct",
    ("nullValues",      "rows"):    "Missing_Pct",  # treat row-based null as Missing_Pct
    ("rowCount",        "rows"):    "Row_Ct",
    ("duplicateValues", "rows"):    "Dupe_Rows",
    ("duplicateValues", "percent"): "Unique_Pct",
}

# Full set of valid TestGen test_types (sourced from export_data_contract._TEST_TYPE_ODCS and docs map)
_VALID_TESTGEN_TYPES: frozenset[str] = frozenset({
    "Alpha_Trunc", "Avg_Shift", "Combo_Match", "Condition_Flag", "Constant",
    "CUSTOM", "Daily_Record_Ct", "Dec_Trunc", "Distinct_Date_Ct", "Distinct_Value_Ct",
    "Distribution_Shift", "Dupe_Rows", "Email_Format", "Freshness_Trend", "Future_Date_1Y",
    "Incr_Avg_Shift", "LOV_All", "LOV_Match", "Metric_Trend", "Min_Date", "Min_Val",
    "Missing_Pct", "Monthly_Rec_Ct", "Outlier_Pct_Above", "Outlier_Pct_Below",
    "Pattern_Match", "Recency", "Required", "Row_Ct", "Row_Ct_Pct",
    "Schema_Drift", "Street_Addr_Pattern", "Table_Freshness", "Timeframe_Combo_Gain",
    "Timeframe_Combo_Match", "Unique", "Unique_Pct", "US_State", "Valid_Characters",
    "Valid_Month", "Valid_US_Zip", "Valid_US_Zip3", "Variability_Decrease",
    "Variability_Increase", "Volume_Trend", "Weekly_Rec_Ct",
    "Aggregate_Balance", "Aggregate_Balance_Percent", "Aggregate_Balance_Range",
    "Aggregate_Minimum",
})

# Valid TestGen severity values
_VALID_SEVERITIES: frozenset[str] = frozenset({"Log", "Warning", "Fail", "Error"})

# Governance columns in data_column_chars that may be written by YAML import
_ALLOWED_GOVERNANCE_COLS: frozenset[str] = frozenset({
    "description", "pii_flag", "critical_data_element",
    "data_source", "source_system", "source_process",
    "business_domain", "stakeholder_group", "transform_level",
    "aggregation_level", "data_product",
})

# ODCS classification value → TestGen pii_flag (canonical reverse mapping)
_CLASSIFICATION_TO_PII: dict[str, str] = {
    "confidential": "A/Confidential",
    "internal":     "I/Internal",
    "restricted":   "R/Restricted",
}


def _classification_to_pii_flag(classification: str | None) -> str | None:
    """Reverse of export_data_contract._pii_flag_to_classification."""
    if not classification or classification.lower() == "public":
        return None
    return _CLASSIFICATION_TO_PII.get(classification.lower())

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ThresholdData:
    threshold_value: str | None
    lower_tolerance: str | None
    upper_tolerance: str | None
    test_operator: str | None


@dataclass
class RuleResult:
    """Outcome of processing a single ODCS quality rule."""
    rule_index: int
    action: Literal["create", "update", "no_change", "skip", "error"]
    test_id: str | None = None          # existing id for update; new id after create
    test_type: str | None = None
    updates: dict[str, Any] = field(default_factory=dict)
    insert: dict[str, Any] = field(default_factory=dict)
    warning: str | None = None


@dataclass
class ContractDiff:
    """All changes to apply when importing a contract document."""
    contract_updates: dict[str, Any] = field(default_factory=dict)
    table_group_updates: dict[str, Any] = field(default_factory=dict)
    test_updates: list[dict[str, Any]] = field(default_factory=list)
    test_inserts: list[dict[str, Any]] = field(default_factory=list)   # new tests
    orphaned_ids: list[str] = field(default_factory=list)              # in DB, not in YAML
    # Governance field updates — each entry: {table, col, updates: {db_col: value}}
    governance_updates: list[dict[str, Any]] = field(default_factory=list)
    # Maps quality-list index → new test UUID (populated after apply)
    new_id_by_index: dict[int, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def total_changes(self) -> int:
        return (len(self.contract_updates) + len(self.table_group_updates)
                + len(self.test_updates) + len(self.test_inserts)
                + len(self.governance_updates))

    def summary(self) -> str:
        parts = []
        if self.contract_updates:
            parts.append(f"{len(self.contract_updates)} contract field(s)")
        if self.table_group_updates:
            parts.append(f"{len(self.table_group_updates)} table group field(s)")
        if self.test_updates:
            parts.append(f"{len(self.test_updates)} test update(s)")
        if self.test_inserts:
            parts.append(f"{len(self.test_inserts)} test create(s)")
        return ", ".join(parts) if parts else "no changes"


# ---------------------------------------------------------------------------
# Pure mapping & validation helpers
# ---------------------------------------------------------------------------

def parse_odcs_yaml(raw: str) -> tuple[dict | None, list[str]]:
    """Parse YAML and validate minimum ODCS v3.1.0 structure.

    Returns (doc, errors).  Errors is empty on success.
    """
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

    status = (doc.get("status") or "").lower()
    if status and status not in VALID_STATUSES:
        errors.append(f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}.")

    return doc, errors


def resolve_testgen_type(rule: dict) -> tuple[str | None, str | None]:
    """Determine the TestGen test_type for an ODCS rule.

    Returns (test_type, error_message).
    test_type is None when the rule cannot be mapped.
    """
    rule_type = rule.get("type")

    if rule_type == "text":
        return None, None  # silently skip

    if rule_type == "sql":
        return "CUSTOM", None

    if rule_type == "custom":
        vendor = rule.get("vendor") or rule.get("engine") or ""
        if vendor != "testgen":
            return None, f"type:custom with engine/vendor '{vendor}' is not supported by TestGen import."
        test_type = rule.get("testType")
        if not test_type:
            return None, "type:custom vendor:testgen requires a 'testType' field."
        if test_type not in _VALID_TESTGEN_TYPES:
            return None, f"testType '{test_type}' is not a recognized TestGen test type."
        return test_type, None

    if rule_type == "library":
        metric = rule.get("metric")
        unit = (rule.get("unit") or "rows").lower()
        args = rule.get("arguments") or {}

        if metric is None:
            return None, "type:library requires a 'metric' field."

        if metric == "missingValues":
            return None, "metric:missingValues has no TestGen equivalent (TestGen checks SQL NULL only)."

        if metric == "invalidValues":
            if args.get("pattern"):
                return "Pattern_Match", None
            valid_values = args.get("validValues")
            if valid_values is not None and len(valid_values) > 0:
                return "LOV_Match", None
            if valid_values is not None:
                # present but empty list
                return None, "metric:invalidValues arguments.validValues is empty — cannot create a valid-values test with no allowed values."
            return None, (
                "metric:invalidValues requires arguments.validValues or arguments.pattern to create a TestGen test."
            )

        if metric == "rowCount" and unit == "percent":
            return None, "metric:rowCount with unit:percent has no defined semantics in TestGen; use unit:rows."

        mapped = _METRIC_UNIT_TO_TYPE.get((metric, unit))
        if mapped:
            return mapped, None

        return None, f"metric:'{metric}' with unit:'{unit}' has no TestGen test type mapping."

    if rule_type is None:
        return None, "Rule is missing required 'type' field."

    return None, f"Unrecognized rule type '{rule_type}'."


def extract_threshold(rule: dict) -> tuple[ThresholdData | None, str | None]:
    """Extract threshold/tolerance data from an ODCS rule.

    Returns (ThresholdData, error_message).
    """
    # Check for unsupported operators first
    if "mustNotBeBetween" in rule:
        return None, "Operator 'mustNotBeBetween' is not supported by TestGen import."
    if "mustNotBe" in rule:
        return None, "Operator 'mustNotBe' is not supported by TestGen import."

    if "mustBeBetween" in rule:
        val = rule["mustBeBetween"]
        if not isinstance(val, list):
            return None, "mustBeBetween must be a two-element array [low, high]."
        if len(val) != 2:
            return None, f"mustBeBetween must have exactly 2 elements, got {len(val)}."
        try:
            lo, hi = float(val[0]), float(val[1])
        except (TypeError, ValueError):
            return None, "mustBeBetween bounds must be numeric."
        if lo > hi:
            return None, f"mustBeBetween lower ({val[0]}) must be <= upper ({val[1]})."
        return ThresholdData(
            threshold_value=None,
            lower_tolerance=str(lo),
            upper_tolerance=str(hi),
            test_operator="between",
        ), None

    for op in _SCALAR_OPERATORS:
        if op in rule:
            try:
                val = float(rule[op])
            except (TypeError, ValueError):
                return None, f"Threshold value for '{op}' must be numeric, got: {rule[op]!r}."
            return ThresholdData(
                threshold_value=str(val),
                lower_tolerance=None,
                upper_tolerance=None,
                test_operator=_OPERATOR_TO_DB[op],
            ), None

    return None, "No threshold operator found (mustBe, mustBeGreaterThan, etc.)."


def format_lov_baseline(values: list[str]) -> str:
    """Convert ['active', 'pending'] → ('active','pending') for LOV_Match baseline_value.

    Raises ValueError for empty input — an empty LOV is not a valid constraint.
    """
    if not values:
        raise ValueError("format_lov_baseline: values list must not be empty")
    escaped = [v.replace("'", "''") for v in values]
    return "(" + ",".join(f"'{v}'" for v in escaped) + ")"


def parse_element(element: str | None) -> tuple[str | None, str | None]:
    """Split 'schema.table.column' or 'table.column' or 'table' into (table, column).

    Strips schema prefix if present (3-part path).
    Returns (table_name, column_name).  column_name is None for table-level tests.
    """
    if not element:
        return None, None
    parts = element.split(".")
    if len(parts) == 1:
        return parts[0], None
    if len(parts) == 2:
        return parts[0], parts[1]
    # 3 parts: schema.table.column — drop schema
    return parts[1], parts[2]


def validate_severity(value: str | None) -> str:
    """Return the severity if valid, else 'Fail' (and caller should warn)."""
    if value is None:
        return "Fail"
    # Case-insensitive match
    for s in _VALID_SEVERITIES:
        if s.lower() == value.lower():
            return s
    return "Fail"  # fallback


def build_test_insert(
    *,
    test_type: str,
    threshold: ThresholdData,
    suite_id: str,
    schema_name: str,
    table_name: str,
    column_name: str | None,
    severity: str,
    description: str | None,
    rule: dict,
) -> dict[str, Any]:
    """Build the test_definitions INSERT dict for a new test.

    Does not include 'id' — caller generates and assigns it.
    """
    insert: dict[str, Any] = {
        "test_suite_id": suite_id,
        "test_type": test_type,
        "schema_name": schema_name,
        "table_name": table_name,
        "column_name": column_name,
        "severity": severity,
        "test_description": description,
        "test_active": "Y",
        "lock_refresh": "Y",
        "threshold_value": threshold.threshold_value,
        "lower_tolerance": threshold.lower_tolerance,
        "upper_tolerance": threshold.upper_tolerance,
    }

    args = rule.get("arguments") or {}

    if test_type == "Pattern_Match":
        insert["baseline_value"] = args.get("pattern")

    elif test_type == "LOV_Match":
        valid_values = args.get("validValues") or []
        insert["baseline_value"] = format_lov_baseline(valid_values) if valid_values else None

    elif test_type == "CUSTOM":
        insert["custom_query"] = rule.get("query")
        # For CUSTOM, threshold_value holds skip_errors (max allowed failures)
        # mustBeLessOrEqualTo is the canonical operator for skip_errors
        skip_raw = rule.get("mustBeLessOrEqualTo", 0)
        try:
            insert["skip_errors"] = int(float(skip_raw))
        except (TypeError, ValueError):
            insert["skip_errors"] = 0
        insert["threshold_value"] = None  # CUSTOM uses skip_errors, not threshold_value

    return {k: v for k, v in insert.items() if v is not None}


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def _process_update_rule(
    rule: dict,
    current_test: dict,
    rule_index: int,
) -> RuleResult:
    """Process a rule that has an existing test id (UPDATE path)."""
    test_id = rule["id"]
    updates: dict[str, Any] = {"id": test_id}

    # Detect immutable field changes
    current_type = current_test.get("test_type", "")
    inferred_type, _ = resolve_testgen_type(rule)
    if inferred_type and inferred_type != current_type:
        return RuleResult(
            rule_index=rule_index,
            action="skip",
            test_id=test_id,
            warning=(
                f"Rule '{rule.get('name', test_id)}': changing metric/type would change test_type "
                f"from '{current_type}' to '{inferred_type}' — immutable on existing tests. "
                "Remove the 'id' field to create a new test."
            ),
        )

    current_element = (
        f"{current_test.get('table_name')}.{current_test.get('column_name')}"
        if current_test.get("column_name")
        else current_test.get("table_name")
    )
    # Use parse_element so "schema.table.column" normalises to "table.column" before comparison
    _tbl, _col = parse_element(rule.get("element"))
    rule_element_normalized = f"{_tbl}.{_col}" if _col else _tbl
    if rule_element_normalized and current_element and rule_element_normalized != current_element:
        return RuleResult(
            rule_index=rule_index,
            action="skip",
            test_id=test_id,
            warning=(
                f"Rule '{rule.get('name', test_id)}': changing element from "
                f"'{current_element}' to '{rule_element_normalized}' is immutable. "
                "Remove the 'id' field to create a new test on the new element."
            ),
        )

    # description / name
    imported_name = rule.get("name")
    if imported_name and imported_name != current_test.get("test_description"):
        updates["test_description"] = imported_name

    # threshold
    if current_test.get("test_type") != "CUSTOM":
        thresh, err = extract_threshold(rule)
        if err is None and thresh is not None:
            if thresh.lower_tolerance is not None:
                if thresh.lower_tolerance != current_test.get("lower_tolerance"):
                    updates["lower_tolerance"] = thresh.lower_tolerance
                if thresh.upper_tolerance != current_test.get("upper_tolerance"):
                    updates["upper_tolerance"] = thresh.upper_tolerance
                # clear threshold_value if switching to range
                if current_test.get("threshold_value"):
                    updates["threshold_value"] = None
            else:
                if thresh.threshold_value != current_test.get("threshold_value"):
                    updates["threshold_value"] = thresh.threshold_value
                # clear tolerances if switching to scalar
                if current_test.get("lower_tolerance"):
                    updates["lower_tolerance"] = None
                if current_test.get("upper_tolerance"):
                    updates["upper_tolerance"] = None

    # severity
    raw_sev = rule.get("severity")
    if raw_sev:
        sev = validate_severity(raw_sev)
        if sev != current_test.get("severity"):
            updates["severity"] = sev

    # CUSTOM-specific fields
    if current_test.get("test_type") == "CUSTOM":
        if rule.get("query") and rule["query"] != current_test.get("custom_query"):
            updates["custom_query"] = rule["query"]
        if "mustBeLessOrEqualTo" in rule:
            try:
                new_skip = int(float(rule["mustBeLessOrEqualTo"]))
                if new_skip != current_test.get("skip_errors"):
                    updates["skip_errors"] = new_skip
            except (TypeError, ValueError):
                pass

    if len(updates) == 1:  # only the 'id' key
        return RuleResult(rule_index=rule_index, action="no_change", test_id=test_id)

    return RuleResult(rule_index=rule_index, action="update", test_id=test_id, updates=updates)


def _process_create_rule(
    rule: dict,
    rule_index: int,
    suite_map: dict[str, dict],  # {suite_id: {test_suite, schema_name, ...}}
    default_suite_id: str | None,
    table_group_schema: str,
) -> RuleResult:
    """Process a rule with no id (CREATE path)."""
    rule_name = rule.get("name") or f"rule[{rule_index}]"

    # Resolve test type
    rule_type = rule.get("type")
    if rule_type == "text":
        return RuleResult(rule_index=rule_index, action="skip")

    test_type, type_err = resolve_testgen_type(rule)
    if type_err is not None:
        return RuleResult(rule_index=rule_index, action="skip", warning=f"Rule '{rule_name}': {type_err}")
    if test_type is None:
        return RuleResult(rule_index=rule_index, action="skip")

    # Extract threshold
    thresh, thresh_err = extract_threshold(rule)
    if thresh_err is not None:
        return RuleResult(rule_index=rule_index, action="skip", warning=f"Rule '{rule_name}': {thresh_err}")
    if thresh is None:
        return RuleResult(rule_index=rule_index, action="skip", warning=f"Rule '{rule_name}': no threshold found.")

    # Validate CUSTOM (sql) rules have a non-empty query
    if test_type == "CUSTOM":
        query = rule.get("query") or ""
        if not query.strip():
            return RuleResult(
                rule_index=rule_index, action="skip",
                warning=f"Rule '{rule_name}': type:sql requires a non-empty 'query' field.",
            )

    # Resolve element (table + column)
    element = rule.get("element")
    table_name, column_name = parse_element(element)
    if not table_name and test_type != "CUSTOM":
        return RuleResult(
            rule_index=rule_index, action="skip",
            warning=f"Rule '{rule_name}': CREATE requires an 'element' field to determine table/column.",
        )

    # Resolve suite
    suite_id_from_rule = rule.get("suiteId")
    if suite_id_from_rule:
        if suite_id_from_rule not in suite_map:
            return RuleResult(
                rule_index=rule_index, action="skip",
                warning=f"Rule '{rule_name}': suiteId '{suite_id_from_rule}' not found in table group.",
            )
        suite_id = suite_id_from_rule
    elif default_suite_id:
        suite_id = default_suite_id
    else:
        return RuleResult(
            rule_index=rule_index, action="skip",
            warning=f"Rule '{rule_name}': no suiteId provided and no default suite available.",
        )

    # Resolve schema name from suite
    schema_name = suite_map.get(suite_id, {}).get("schema_name") or table_group_schema

    # Severity
    raw_sev = rule.get("severity")
    severity = validate_severity(raw_sev)
    sev_warning: str | None = None
    if raw_sev and severity != raw_sev:
        sev_warning = f"Rule '{rule_name}': severity '{raw_sev}' is not valid; defaulting to 'Fail'."

    # Build insert
    insert = build_test_insert(
        test_type=test_type,
        threshold=thresh,
        suite_id=suite_id,
        schema_name=schema_name,
        table_name=table_name or "",
        column_name=column_name,
        severity=severity,
        description=rule.get("name"),
        rule=rule,
    )

    return RuleResult(
        rule_index=rule_index,
        action="create",
        test_type=test_type,
        insert=insert,
        warning=sev_warning,
    )


def compute_import_diff(doc: dict, table_group_id: str, schema: str) -> ContractDiff:
    """Compare ODCS document against DB state and build a full diff (updates + creates)."""
    diff = ContractDiff()

    # Fetch table group
    group_rows = fetch_dict_from_db(
        f"""
        SELECT id, table_groups_name, description,
               contract_version, contract_status,
               business_domain, data_product, profiling_delay_days,
               table_group_schema
        FROM {schema}.table_groups
        WHERE id = :tg_id
        """,
        params={"tg_id": table_group_id},
    )
    if not group_rows:
        diff.errors.append(f"Table group '{table_group_id}' not found.")
        return diff

    current = dict(group_rows[0])
    table_group_schema: str = current.get("table_group_schema") or ""

    # --- fundamentals ---
    if doc.get("version") and doc["version"] != current.get("contract_version"):
        diff.contract_updates["contract_version"] = doc["version"]

    imported_status = (doc.get("status") or "").lower()
    if imported_status and imported_status != current.get("contract_status"):
        diff.contract_updates["contract_status"] = imported_status

    purpose = (
        (doc.get("description") or {}).get("purpose")
        if isinstance(doc.get("description"), dict)
        else None
    )
    if purpose and purpose != current.get("description"):
        diff.contract_updates["description"] = purpose

    if doc.get("domain") and doc["domain"] != current.get("business_domain"):
        diff.table_group_updates["business_domain"] = doc["domain"]

    if doc.get("dataProduct") and doc["dataProduct"] != current.get("data_product"):
        diff.table_group_updates["data_product"] = doc["dataProduct"]

    for sla in doc.get("slaProperties") or []:
        if sla.get("property") == "latency" and sla.get("unit") in ("day", "d"):
            try:
                new_delay = int(sla["value"])
                if new_delay != current.get("profiling_delay_days"):
                    diff.table_group_updates["profiling_delay_days"] = new_delay
            except (TypeError, ValueError):
                diff.warnings.append(f"Could not parse latency SLA value: {sla.get('value')}")

    # --- quality rules ---
    if not doc.get("quality"):
        return diff

    # Fetch existing tests
    test_rows = fetch_dict_from_db(
        f"""
        SELECT td.id, td.test_type, td.test_description, td.test_active,
               td.threshold_value, td.lower_tolerance, td.upper_tolerance,
               td.custom_query, td.skip_errors, td.severity,
               td.table_name, td.column_name
        FROM {schema}.test_definitions td
        JOIN {schema}.test_suites s ON s.id = td.test_suite_id
        WHERE s.table_groups_id = :tg_id
          AND COALESCE(s.include_in_contract, TRUE) IS NOT FALSE
          AND td.test_active = 'Y'
        """,
        params={"tg_id": table_group_id},
    )
    current_tests: dict[str, dict] = {str(r["id"]): dict(r) for r in test_rows}

    # Fetch available suites (for create path suite resolution)
    suite_rows = fetch_dict_from_db(
        f"""
        SELECT s.id::text AS suite_id, s.test_suite, tg.table_group_schema AS schema_name
        FROM {schema}.test_suites s
        JOIN {schema}.table_groups tg ON tg.id = s.table_groups_id
        WHERE s.table_groups_id = :tg_id
          AND COALESCE(s.include_in_contract, TRUE) IS NOT FALSE
          AND COALESCE(s.is_monitor, FALSE) IS NOT TRUE
        ORDER BY LOWER(s.test_suite)
        """,
        params={"tg_id": table_group_id},
    )
    suite_map: dict[str, dict] = {str(r["suite_id"]): dict(r) for r in suite_rows}
    default_suite_id: str | None = next(iter(suite_map), None)

    # Track which test IDs are referenced in YAML (for orphan detection)
    yaml_referenced_ids: set[str] = set()
    seen_yaml_ids: set[str] = set()

    for idx, rule in enumerate(doc["quality"]):
        rule_id = rule.get("id")

        if rule_id:
            if rule_id in seen_yaml_ids:
                diff.warnings.append(
                    f"Quality rule id '{rule_id}' appears more than once in YAML — duplicate skipped."
                )
                continue
            seen_yaml_ids.add(rule_id)
            yaml_referenced_ids.add(rule_id)
            if rule_id not in current_tests:
                diff.warnings.append(
                    f"Quality rule id '{rule_id}' not found in table group — may have been deleted. Skipped."
                )
                continue
            result = _process_update_rule(rule, current_tests[rule_id], idx)
        else:
            result = _process_create_rule(rule, idx, suite_map, default_suite_id, table_group_schema)

        if result.warning:
            diff.warnings.append(result.warning)

        if result.action == "update":
            diff.test_updates.append(result.updates)
        elif result.action == "create":
            diff.test_inserts.append({**result.insert, "_rule_index": idx})

    # Orphan detection
    for test_id in current_tests:
        if test_id not in yaml_referenced_ids:
            diff.orphaned_ids.append(test_id)
            diff.warnings.append(
                f"Test '{test_id}' (type: {current_tests[test_id].get('test_type')}) "
                "is in the table group but not in YAML — not deleted."
            )

    # --- schema governance round-trip ---
    # Read current data_column_chars values for comparison so we only write actual changes.
    if doc.get("schema"):
        gov_rows = fetch_dict_from_db(
            f"""
            SELECT table_name, column_name,
                   description, pii_flag, critical_data_element,
                   data_source, source_system, source_process,
                   business_domain, stakeholder_group, transform_level,
                   aggregation_level, data_product
            FROM {schema}.data_column_chars
            WHERE table_groups_id = :tg_id
            """,
            params={"tg_id": table_group_id},
        )
        current_gov: dict[tuple[str, str], dict[str, Any]] = {
            (str(r["table_name"]), str(r["column_name"])): dict(r)
            for r in gov_rows
        }

        for schema_entry in doc["schema"]:
            table_name = schema_entry.get("name") or ""
            for prop in (schema_entry.get("properties") or []):
                col_name = prop.get("name") or ""
                if not table_name or not col_name:
                    continue
                cur = current_gov.get((table_name, col_name), {})
                updates: dict[str, Any] = {}

                # Standard ODCS governance fields
                if "description" in prop and prop["description"] != cur.get("description"):
                    updates["description"] = prop["description"]

                if "criticalDataElement" in prop:
                    new_val = bool(prop["criticalDataElement"])
                    if new_val != bool(cur.get("critical_data_element")):
                        updates["critical_data_element"] = new_val

                if "classification" in prop:
                    # Prefer testgen.pii_flag from customProperties for exact round-trip
                    pii_val = None
                    for cp in (prop.get("customProperties") or []):
                        if cp.get("property") == "testgen.pii_flag":
                            pii_val = cp.get("value")
                            break
                    if pii_val is None:
                        pii_val = _classification_to_pii_flag(prop["classification"])
                    if pii_val != cur.get("pii_flag"):
                        updates["pii_flag"] = pii_val

                # TestGen customProperties — testgen.* tags and profiling metadata
                for cp in (prop.get("customProperties") or []):
                    key = cp.get("property") or ""
                    if not key.startswith("testgen."):
                        continue
                    db_col = key[len("testgen."):]
                    if db_col not in _ALLOWED_GOVERNANCE_COLS:
                        continue
                    if db_col in ("pii_flag", "critical_data_element"):
                        continue  # already handled above
                    new_val = cp.get("value")
                    if new_val != cur.get(db_col):
                        updates[db_col] = new_val

                if updates:
                    diff.governance_updates.append({
                        "table": table_name,
                        "col":   col_name,
                        "updates": updates,
                    })

    return diff


# ---------------------------------------------------------------------------
# Apply diff
# ---------------------------------------------------------------------------

_ALLOWED_GROUP_COLS: frozenset[str] = frozenset({
    "contract_version", "contract_status", "description",
    "business_domain", "data_product", "profiling_delay_days",
})

_ALLOWED_TEST_UPDATE_COLS: frozenset[str] = frozenset({
    "test_description", "threshold_value", "lower_tolerance",
    "upper_tolerance", "severity", "custom_query", "skip_errors",
})
# Public alias for callers that use the legacy name (e.g. data_contract_queries)
_ALLOWED_TEST_COLS: frozenset[str] = _ALLOWED_TEST_UPDATE_COLS

_ALLOWED_TEST_INSERT_COLS: frozenset[str] = frozenset({
    "test_suite_id", "test_type", "schema_name", "table_name", "column_name",
    "test_description", "test_active", "lock_refresh", "severity",
    "threshold_value", "lower_tolerance", "upper_tolerance",
    "baseline_value", "custom_query", "skip_errors",
})


def apply_import_diff(
    diff: ContractDiff,
    table_group_id: str,
    schema: str,
    yaml_path: str | None = None,
) -> None:
    """Write diff to DB and optionally write back new test IDs to the YAML file.

    Args:
        diff: The diff to apply (must have no errors).
        table_group_id: UUID of the target table group.
        schema: DB schema name.
        yaml_path: If provided, mutate this file in place with new test IDs after creates.
    """
    if diff.has_errors:
        raise ValueError(f"Cannot apply diff with errors: {diff.errors}")

    db_queries: list[tuple[str, dict]] = []

    # Group updates (contract_updates + table_group_updates both target table_groups)
    all_group_updates = {**diff.contract_updates, **diff.table_group_updates}
    if all_group_updates:
        invalid = set(all_group_updates) - _ALLOWED_GROUP_COLS
        if invalid:
            raise ValueError(f"Unexpected table_groups columns in diff: {invalid}")
        params: dict[str, Any] = {"tg_id": table_group_id}
        set_parts = []
        for col, val in all_group_updates.items():
            pname = f"p_{col}"
            set_parts.append(f"{col} = :{pname}")
            params[pname] = val
        db_queries.append((
            f"UPDATE {schema}.table_groups SET {', '.join(set_parts)} WHERE id = :tg_id",
            params,
        ))

    # Test updates
    for test_update in diff.test_updates:
        upd = dict(test_update)
        test_id = upd.pop("id")
        if not upd:
            continue
        invalid = set(upd) - _ALLOWED_TEST_UPDATE_COLS
        if invalid:
            raise ValueError(f"Unexpected test_definitions columns in update: {invalid}")
        params = {"test_id": test_id, "lock_y": "Y"}
        set_parts = []
        for col, val in upd.items():
            pname = f"p_{col}"
            set_parts.append(f"{col} = :{pname}")
            params[pname] = val
        db_queries.append((
            f"UPDATE {schema}.test_definitions "
            f"SET {', '.join(set_parts)}, last_manual_update = NOW(), lock_refresh = :lock_y "
            f"WHERE id = :test_id",
            params,
        ))

    # Test inserts — generate UUIDs now so we can write them back
    for insert_dict in diff.test_inserts:
        ins = dict(insert_dict)
        rule_index: int = ins.pop("_rule_index")
        new_id = str(uuid.uuid4())
        ins["id"] = new_id
        diff.new_id_by_index[rule_index] = new_id

        invalid = set(ins) - (_ALLOWED_TEST_INSERT_COLS | {"id"})
        if invalid:
            raise ValueError(f"Unexpected test_definitions columns in insert: {invalid}")

        cols = ", ".join(ins.keys())
        placeholders = ", ".join(f":{k}" for k in ins.keys())
        db_queries.append((
            f"INSERT INTO {schema}.test_definitions ({cols}) VALUES ({placeholders})",
            {k: (str(v) if k == "id" else v) for k, v in ins.items()},
        ))

    if db_queries:
        execute_db_queries(db_queries)

    # Governance updates → data_column_chars
    for gov in diff.governance_updates:
        upd = {k: v for k, v in gov.get("updates", {}).items() if k in _ALLOWED_GOVERNANCE_COLS}
        if not upd:
            continue
        params_gov: dict[str, Any] = {
            "tg_id": table_group_id,
            "tbl":   gov["table"],
            "col":   gov["col"],
        }
        set_parts_gov = []
        for col_name, val in upd.items():
            pname = f"p_{col_name}"
            set_parts_gov.append(f"{col_name} = :{pname}")
            params_gov[pname] = val
        execute_db_queries([(
            f"UPDATE {schema}.data_column_chars "
            f"SET {', '.join(set_parts_gov)} "
            f"WHERE table_groups_id = CAST(:tg_id AS uuid) "
            f"AND table_name = :tbl AND column_name = :col",
            params_gov,
        )])


    # Write-back: mutate YAML file with new test IDs
    if yaml_path and diff.new_id_by_index:
        _write_back_ids(yaml_path, diff.new_id_by_index)


def _write_back_ids(yaml_path: str, index_to_id: dict[int, str]) -> None:
    """Reload YAML file and insert new test IDs at the specified rule indices."""
    with open(yaml_path) as f:
        raw = f.read()

    updated = get_updated_yaml(raw, index_to_id)
    if updated == raw:
        LOG.warning("write_back_ids: could not re-parse YAML at %s", yaml_path)
        return

    with open(yaml_path, "w") as f:
        f.write(updated)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@with_database_session
def run_import_contract(
    yaml_content: str,
    table_group_id: str,
    dry_run: bool = False,
    yaml_path: str | None = None,
) -> ContractDiff:
    """Parse an ODCS contract YAML and apply it to the given table group.

    Args:
        yaml_content: Raw YAML string.
        table_group_id: UUID of the target table group.
        dry_run: If True, compute and return the diff without writing to DB.
        yaml_path: Path to the source YAML file; if provided and not dry_run,
                   new test IDs are written back into this file.

    Returns:
        ContractDiff describing what was (or would be) changed.
    """
    schema = get_tg_schema()

    doc, errors = parse_odcs_yaml(yaml_content)
    if errors:
        diff = ContractDiff()
        diff.errors.extend(errors)
        return diff

    diff = compute_import_diff(doc, table_group_id, schema)

    if dry_run or diff.has_errors:
        return diff

    apply_import_diff(diff, table_group_id, schema, yaml_path=yaml_path)
    return diff


def get_updated_yaml(original_yaml: str, index_to_id: dict[int, str]) -> str:
    """Return a copy of *original_yaml* with new test IDs inserted at the given rule indices.

    Used in browser/upload contexts where writing back to a file is not possible.

    Args:
        original_yaml: Raw YAML string from the uploaded file.
        index_to_id: Mapping of quality-rule list index → newly created test UUID.

    Returns:
        Updated YAML string (comments are lost — PyYAML limitation).
    """
    if not index_to_id:
        return original_yaml

    try:
        doc = yaml.safe_load(original_yaml)
    except yaml.YAMLError:
        return original_yaml
    if not isinstance(doc, dict):
        return original_yaml

    quality = doc.get("quality") or []
    for idx, new_id in index_to_id.items():
        if idx < len(quality):
            quality[idx]["id"] = new_id

    return yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
