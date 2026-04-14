"""
Export a TestGen test suite as an Open Data Contract Standard (ODCS) v3.1.0 document.

Spec reference: https://bitol-io.github.io/open-data-contract-standard/v3.1.0/
"""
from __future__ import annotations

import io
import logging
import sys
from datetime import UTC, datetime
from typing import Any

import yaml

from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import fetch_dict_from_db
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")

# Column-level governance tag fields in data_column_chars — exported as testgen.* customProperties
_TAG_FIELDS: tuple[str, ...] = (
    "data_source", "source_system", "source_process",
    "business_domain", "stakeholder_group", "transform_level",
    "aggregation_level", "data_product",
)

# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------

# TestGen functional_data_type → ODCS logicalType
_FUNCTIONAL_TO_LOGICAL: dict[str, str] = {
    "Date Stamp": "date",
    "DateTime Stamp": "timestamp",
    "Process Date Stamp": "date",
    "Process DateTime Stamp": "timestamp",
    "Historical Date": "date",
    "Future Date": "date",
    "Schedule Date": "date",
    "Transactional Date": "date",
    "Transactional Date (Wk)": "date",
    "Transactional Date (Mo)": "date",
    "Transactional Date (Qtr)": "date",
    "Date (TBD)": "date",
    "Period Year": "integer",
    "Period Month": "integer",
    "Period Week": "integer",
    "Period DOW": "integer",
    "Period Year-Mon": "string",
    "Period Mon-NN": "string",
    "Boolean": "boolean",
    "Measurement": "number",
    "Measurement Discrete": "integer",
    "Measurement Spike": "number",
    "Measurement Pct": "number",
    "Measurement Text": "number",
    "Attribute-Numeric": "number",
    "Sequence": "integer",
    "ID": "string",
    "ID-SK": "string",
    "ID-Unique": "string",
    "ID-Unique-SK": "string",
    "ID-Secondary": "string",
    "ID-FK": "string",
    "ID-Group": "string",
    "Email": "string",
    "Phone": "string",
    "Address": "string",
    "State": "string",
    "City": "string",
    "Zip": "string",
    "Person Full Name": "string",
    "Person Given Name": "string",
    "Person Last Name": "string",
    "Entity Name": "string",
    "Code": "string",
    "Category": "string",
    "Flag": "string",
    "Constant": "string",
    "Process User": "string",
    "System User": "string",
    "Attribute": "string",
    "Description": "string",
}

FUNCTIONAL_TYPE_TO_LOGICAL = _FUNCTIONAL_TO_LOGICAL

# TestGen std_pattern_match → ODCS logicalTypeOptions.format
_PATTERN_TO_FORMAT: dict[str, str] = {
    "EMAIL": "email",
    "ZIP_USA": "zip-us",
    "STATE_USA": "state-us",
    "PHONE_USA": "phone-us",
    "SSN": "ssn-us",
    "CREDIT_CARD": "credit-card",
    "STREET_ADDR": "street-address-us",
    "FILE_NAME": "file-name",
    "DELIMITED_DATA": "delimited",
}

# Documentation base URLs
_DOCS_BASE = "https://docs.datakitchen.io/testgen/generate-tests/test-types"
_DOCS_MONITOR_BASE = "https://docs.datakitchen.io/testgen/monitor-tables"

# TestGen test_type → documentation URL (only types with confirmed docs pages are included)
_TEST_TYPE_DOCS_URL: dict[str, str] = {
    # Validity
    "Alpha_Trunc":          f"{_DOCS_BASE}/validity-tests/#alpha-truncation",
    "Combo_Match":          f"{_DOCS_BASE}/validity-tests/#pattern-match",
    "Distinct_Value_Ct":    f"{_DOCS_BASE}/validity-tests/#value-count",
    "Email_Format":         f"{_DOCS_BASE}/validity-tests/#email-format",
    "Min_Date":             f"{_DOCS_BASE}/validity-tests/#minimum-date",
    "Min_Val":              f"{_DOCS_BASE}/validity-tests/#minimum-value",
    "Pattern_Match":        f"{_DOCS_BASE}/validity-tests/#pattern-match",
    "Street_Addr_Pattern":  f"{_DOCS_BASE}/validity-tests/#street-address",
    "US_State":             f"{_DOCS_BASE}/validity-tests/#us-state",
    "Valid_Characters":     f"{_DOCS_BASE}/validity-tests/#valid-characters",
    "Valid_Month":          f"{_DOCS_BASE}/validity-tests/#valid-month",
    "Valid_US_Zip":         f"{_DOCS_BASE}/validity-tests/#valid-us-zip",
    "Valid_US_Zip3":        f"{_DOCS_BASE}/validity-tests/#valid-us-zip-3",
    # Completeness
    "Daily_Record_Ct":      f"{_DOCS_BASE}/completeness-tests/#daily-records",
    "Missing_Pct":          f"{_DOCS_BASE}/completeness-tests/#percent-missing",
    "Monthly_Rec_Ct":       f"{_DOCS_BASE}/completeness-tests/#monthly-records",
    "Required":             f"{_DOCS_BASE}/completeness-tests/#required-entry",
    "Row_Ct":               f"{_DOCS_BASE}/completeness-tests/#row-count",
    "Row_Ct_Pct":           f"{_DOCS_BASE}/completeness-tests/#row-range",
    "Weekly_Rec_Ct":        f"{_DOCS_BASE}/completeness-tests/#weekly-records",
    # Consistency
    "Aggregate_Balance":         f"{_DOCS_BASE}/consistency-tests/#aggregate-balance",
    "Aggregate_Balance_Percent": f"{_DOCS_BASE}/consistency-tests/#aggregate-balance-percent",
    "Aggregate_Balance_Range":   f"{_DOCS_BASE}/consistency-tests/#aggregate-balance-range",
    "Aggregate_Minimum":         f"{_DOCS_BASE}/consistency-tests/#aggregate-minimum",
    "Avg_Shift":                 f"{_DOCS_BASE}/consistency-tests/#average-shift",
    "Constant":                  f"{_DOCS_BASE}/consistency-tests/#constant-match",
    "Condition_Flag":            f"{_DOCS_BASE}/consistency-tests/#custom-condition",
    "Dec_Trunc":                 f"{_DOCS_BASE}/consistency-tests/#decimal-truncation",
    "Distribution_Shift":        f"{_DOCS_BASE}/consistency-tests/#distribution-shift",
    "LOV_All":                   f"{_DOCS_BASE}/consistency-tests/#value-match-all",
    "Timeframe_Combo_Match":     f"{_DOCS_BASE}/consistency-tests/#timeframe-match",
    "Timeframe_Combo_Gain":      f"{_DOCS_BASE}/consistency-tests/#timeframe-no-drops",
    # Timeliness
    "Distinct_Date_Ct":     f"{_DOCS_BASE}/timeliness-tests/#date-count",
    "Future_Date_1Y":       f"{_DOCS_BASE}/timeliness-tests/#future-year",
    "Recency":              f"{_DOCS_BASE}/timeliness-tests/#recency",
    "Table_Freshness":      f"{_DOCS_BASE}/timeliness-tests/#table-freshness",
    # Accuracy
    "CUSTOM":               f"{_DOCS_BASE}/accuracy-tests/#custom-test",
    "Incr_Avg_Shift":       f"{_DOCS_BASE}/accuracy-tests/#new-shift",
    "Outlier_Pct_Above":    f"{_DOCS_BASE}/accuracy-tests/#outliers-above",
    "Outlier_Pct_Below":    f"{_DOCS_BASE}/accuracy-tests/#outliers-below",
    "Variability_Decrease": f"{_DOCS_BASE}/accuracy-tests/#variability-decrease",
    "Variability_Increase": f"{_DOCS_BASE}/accuracy-tests/#variability-increase",
    # Uniqueness
    "Dupe_Rows":    f"{_DOCS_BASE}/uniqueness-tests/#duplicate-rows",
    "Unique":       f"{_DOCS_BASE}/uniqueness-tests/#unique-values",
    "Unique_Pct":   f"{_DOCS_BASE}/uniqueness-tests/#percent-unique",
    # Monitors
    "Freshness_Trend": f"{_DOCS_MONITOR_BASE}/#freshness",
    "Metric_Trend":    f"{_DOCS_MONITOR_BASE}/#metric",
    "Schema_Drift":    f"{_DOCS_MONITOR_BASE}/#schema",
    "Volume_Trend":    f"{_DOCS_MONITOR_BASE}/#volume",
}

# TestGen dq_dimension → ODCS quality dimension
_DQ_DIMENSION_MAP: dict[str, str] = {
    "Accuracy": "accuracy",
    "Completeness": "completeness",
    "Consistency": "consistency",
    "Coverage": "coverage",
    "Freshness": "timeliness",
    "Timeliness": "timeliness",
    "Uniqueness": "uniqueness",
    "Validity": "conformity",
}

# TestGen test_type → ODCS quality rule shape
# Keys: odcs_type, metric (for library), operator, unit
_TEST_TYPE_ODCS: dict[str, dict[str, str]] = {
    "CUSTOM":            {"odcs_type": "sql",     "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
    "Missing_Pct":       {"odcs_type": "library", "metric": "nullValues",       "operator": "mustBeLessOrEqualTo",    "unit": "percent"},
    "Row_Ct":            {"odcs_type": "library", "metric": "rowCount",         "operator": "mustBeGreaterOrEqualTo", "unit": "rows"},
    "Daily_Record_Ct":   {"odcs_type": "library", "metric": "rowCount",         "operator": "mustBeGreaterOrEqualTo", "unit": "rows"},
    "Monthly_Rec_Ct":    {"odcs_type": "library", "metric": "rowCount",         "operator": "mustBeGreaterOrEqualTo", "unit": "rows"},
    "Weekly_Rec_Ct":     {"odcs_type": "library", "metric": "rowCount",         "operator": "mustBeGreaterOrEqualTo", "unit": "rows"},
    "Dupe_Rows":         {"odcs_type": "library", "metric": "duplicateValues",  "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
    "Unique_Pct":        {"odcs_type": "library", "metric": "duplicateValues",  "operator": "mustBeGreaterOrEqualTo", "unit": "percent"},
    "Distinct_Value_Ct": {"odcs_type": "library", "metric": "duplicateValues",  "operator": "mustBeGreaterOrEqualTo", "unit": "rows"},
    "Email_Format":      {"odcs_type": "library", "metric": "invalidValues",    "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
    "Valid_US_Zip":      {"odcs_type": "library", "metric": "invalidValues",    "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
    "Valid_US_Zip3":     {"odcs_type": "library", "metric": "invalidValues",    "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
    "LOV_Match":         {"odcs_type": "library", "metric": "invalidValues",    "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
    "LOV_All":           {"odcs_type": "library", "metric": "invalidValues",    "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
    "Pattern_Match":     {"odcs_type": "library", "metric": "invalidValues",    "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
    "Street_Addr_Pattern": {"odcs_type": "library", "metric": "invalidValues", "operator": "mustBeLessOrEqualTo",    "unit": "rows"},
}
_TEST_TYPE_ODCS_DEFAULT = {"odcs_type": "custom", "vendor": "testgen", "operator": "mustBeLessOrEqualTo", "unit": "rows"}

# ODCS contract lifecycle statuses
VALID_STATUSES = {"proposed", "draft", "active", "deprecated", "retired"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pii_flag_to_classification(pii_flag: str | None) -> str:
    if not pii_flag:
        return "public"
    prefix = pii_flag.split("/")[0]
    return "confidential" if prefix == "A" else "restricted"



def _derive_origin(last_auto_gen_date: Any, last_manual_update: Any, lock_refresh: str | None, test_type: str) -> str:
    if test_type == "CUSTOM":
        return "business_rule"
    if lock_refresh == "Y":
        return "business_rule"
    if last_auto_gen_date and last_manual_update and last_manual_update > last_auto_gen_date:
        return "business_rule"
    if last_auto_gen_date:
        return "auto_generated"
    return "manual"


def _result_status_to_odcs(status: str | None) -> str | None:
    return {"Passed": "passing", "Failed": "failing", "Warning": "warning", "Error": "error"}.get(status or "", None)


def _nonempty(value: Any) -> Any:
    """Return value only if truthy, else None — keeps YAML clean."""
    return value if value else None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------

def _fetch_group_context(table_group_id: str, schema: str) -> dict:
    sql = f"""
        SELECT
            g.id                       AS table_group_id,
            g.table_groups_name,
            g.table_group_schema,
            g.description              AS group_description,
            g.contract_version,
            g.contract_status,
            g.project_code,
            g.business_domain,
            g.data_product,
            g.data_source,
            g.source_system,
            g.source_process,
            g.data_location,
            g.transform_level,
            g.stakeholder_group,
            g.profiling_delay_days,
            c.sql_flavor_code,
            c.project_host,
            c.project_port,
            c.project_db,
            SUM(tr.test_ct)            AS last_run_test_ct,
            SUM(tr.passed_ct)          AS last_run_passed_ct,
            SUM(tr.failed_ct)          AS last_run_failed_ct,
            SUM(tr.warning_ct)         AS last_run_warning_ct,
            SUM(tr.error_ct)           AS last_run_error_ct,
            AVG(tr.dq_score_test_run)  AS last_run_dq_score,
            MAX(tr.test_starttime)     AS last_run_at
        FROM {schema}.table_groups g
        JOIN {schema}.connections c ON c.connection_id = g.connection_id
        LEFT JOIN {schema}.test_suites s ON s.table_groups_id = g.id
        LEFT JOIN {schema}.test_runs tr ON tr.id = s.last_complete_test_run_id
        WHERE g.id = :tg_id
        GROUP BY g.id, g.table_groups_name, g.table_group_schema, g.description,
                 g.contract_version, g.contract_status, g.project_code,
                 g.business_domain, g.data_product, g.data_source, g.source_system,
                 g.source_process, g.data_location, g.transform_level,
                 g.stakeholder_group, g.profiling_delay_days,
                 c.sql_flavor_code, c.project_host, c.project_port, c.project_db
    """
    rows = fetch_dict_from_db(sql, params={"tg_id": table_group_id})
    return dict(rows[0]) if rows else {}


def _fetch_columns(table_group_id: str, schema: str) -> list[dict]:
    sql = f"""
        SELECT
            col.table_name,
            col.column_name,
            col.db_data_type,
            col.general_type,
            col.functional_data_type,
            col.description,
            col.pii_flag,
            col.critical_data_element,
            col.data_source,
            col.source_system,
            col.source_process,
            col.business_domain,
            col.stakeholder_group,
            col.transform_level,
            col.aggregation_level,
            col.data_product,
            pr.null_value_ct,
            pr.record_ct,
            pr.distinct_value_ct,
            pr.distinct_value_ct = pr.record_ct AS all_values_unique,
            pr.min_length,
            pr.max_length,
            pr.min_value,
            pr.max_value,
            pr.top_freq_values,
            pr.std_pattern_match,
            pr.datatype_suggestion
        FROM {schema}.data_column_chars col
        LEFT JOIN {schema}.profile_results pr
            ON  pr.table_groups_id = col.table_groups_id
            AND pr.table_name      = col.table_name
            AND pr.column_name     = col.column_name
            AND pr.profile_run_id  = (
                    SELECT id FROM {schema}.profiling_runs
                    WHERE  table_groups_id = col.table_groups_id
                    AND    status = 'Complete'
                    ORDER  BY profiling_starttime DESC
                    LIMIT  1
                )
        WHERE col.table_groups_id = :tg_id
          AND col.excluded_data_element IS NOT TRUE
        ORDER BY col.table_name, col.column_name
    """
    return [dict(r) for r in fetch_dict_from_db(sql, params={"tg_id": table_group_id})]


def _fetch_test_run_history(table_group_id: str, schema: str, limit: int = 5) -> list[dict]:
    """Return the last N completed test runs across all suites in the table group."""
    sql = f"""
        SELECT
            tr.test_starttime,
            tr.test_endtime,
            tr.test_ct,
            tr.passed_ct,
            tr.failed_ct,
            tr.warning_ct,
            tr.error_ct,
            tr.dq_score_test_run,
            s.test_suite AS suite_name
        FROM {schema}.test_runs tr
        JOIN {schema}.test_suites s ON s.id = tr.test_suite_id
        WHERE s.table_groups_id = :tg_id
          AND s.include_in_contract IS NOT FALSE  -- TRUE or NULL; column is NOT NULL DEFAULT TRUE so NULL only on pre-migration rows
          AND COALESCE(s.is_contract_snapshot, FALSE) IS NOT TRUE
          AND tr.status = 'Complete'
        ORDER BY tr.test_starttime DESC
        LIMIT :limit
    """
    try:
        return [dict(r) for r in fetch_dict_from_db(sql, params={"tg_id": table_group_id, "limit": limit})]
    except Exception:
        return []


def _fetch_suite_scope(table_group_id: str, schema: str) -> dict:
    """Return counts and names of included/excluded suites for the table group."""
    sql = f"""
        SELECT test_suite, COALESCE(include_in_contract, TRUE) AS include_in_contract
        FROM {schema}.test_suites
        WHERE table_groups_id = :tg_id
          AND is_monitor IS NOT TRUE
          AND COALESCE(is_contract_snapshot, FALSE) IS NOT TRUE
        ORDER BY LOWER(test_suite)
    """
    rows = fetch_dict_from_db(sql, params={"tg_id": table_group_id})
    included = [r["test_suite"] for r in rows if r["include_in_contract"]]
    excluded = [r["test_suite"] for r in rows if not r["include_in_contract"]]
    return {
        "included": included,
        "excluded": excluded,
        "total":    len(rows),
    }


def _fetch_tests(table_group_id: str, schema: str) -> list[dict]:
    sql = f"""
        SELECT
            td.id,
            s.id::text                        AS suite_id,
            td.test_type,
            td.schema_name,
            td.table_name,
            td.column_name,
            tt.test_scope,
            td.test_active,
            td.test_description                   AS user_description,
            td.severity,
            td.threshold_value,
            td.baseline_value,
            td.baseline_ct,
            td.lower_tolerance,
            td.upper_tolerance,
            td.subset_condition,
            td.groupby_names,
            td.having_condition,
            td.window_date_column,
            td.window_days,
            td.match_schema_name,
            td.match_table_name,
            td.match_column_names,
            td.custom_query,
            td.skip_errors,
            td.lock_refresh,
            td.last_auto_gen_date,
            td.last_manual_update,
            tt.dq_dimension,
            tt.test_name_short,
            tt.test_description                   AS type_description,
            tt.measure_uom,
            tr.result_status,
            tr.result_measure,
            tr.threshold_value  AS result_threshold,
            tr.result_message,
            tr.test_time        AS result_time
        FROM {schema}.test_definitions td
        JOIN {schema}.test_types tt ON tt.test_type = td.test_type
        JOIN {schema}.test_suites s ON s.id = td.test_suite_id
        LEFT JOIN LATERAL (
            SELECT result_status, result_measure, threshold_value, result_message, test_time
            FROM   {schema}.test_results
            WHERE  test_definition_id = td.id
              AND  disposition != 'Inactive'
            ORDER  BY test_time DESC
            LIMIT  1
        ) tr ON TRUE
        WHERE s.table_groups_id = :tg_id
          AND s.include_in_contract IS NOT FALSE  -- TRUE or NULL; column is NOT NULL DEFAULT TRUE so NULL only on pre-migration rows
          AND COALESCE(s.is_contract_snapshot, FALSE) IS NOT TRUE
          AND td.test_active    = 'Y'
        ORDER BY td.table_name, td.column_name, td.test_type
    """
    return [dict(r) for r in fetch_dict_from_db(sql, params={"tg_id": table_group_id})]


# ---------------------------------------------------------------------------
# ODCS builders
# ---------------------------------------------------------------------------

def _build_schema(columns: list[dict]) -> list[dict]:
    tables: dict[str, list[dict]] = {}
    for col in columns:
        tbl = col["table_name"]
        tables.setdefault(tbl, []).append(col)

    result = []
    for table_name, cols in tables.items():
        properties = []
        for col in cols:
            logical_type = _FUNCTIONAL_TO_LOGICAL.get(col.get("functional_data_type") or "", "string")
            prop: dict[str, Any] = {
                "name": col["column_name"],
                "description": _nonempty(col.get("description")),
                "physicalType": _nonempty(col.get("db_data_type")),
                "logicalType": logical_type,
                "required": bool(col.get("record_ct") and col.get("null_value_ct") == 0),
                "criticalDataElement": bool(col.get("critical_data_element")),
                "classification": _pii_flag_to_classification(col.get("pii_flag")) if col.get("pii_flag") else None,
            }

            # Primary key detection — ID-Unique functional type or profiling all-unique indicator
            is_pk = (
                col.get("functional_data_type") == "ID-Unique"
                or bool(col.get("all_values_unique") and col.get("record_ct") and col.get("null_value_ct") == 0)
            )

            # customProperties — TestGen-specific extensions, not part of the ODCS standard.
            # Prefixed with "testgen." so consumers know they are not portable.
            custom_props: list[dict[str, Any]] = []
            if is_pk:
                custom_props.append({"property": "testgen.primaryKey", "value": True})
            if col.get("min_length") is not None:
                custom_props.append({"property": "testgen.minLength", "value": col["min_length"]})
            if col.get("max_length") is not None:
                custom_props.append({"property": "testgen.maxLength", "value": col["max_length"]})
            if col.get("min_value") is not None:
                custom_props.append({"property": "testgen.minimum", "value": _safe_float(col["min_value"])})
            if col.get("max_value") is not None:
                custom_props.append({"property": "testgen.maximum", "value": _safe_float(col["max_value"])})
            fmt = _PATTERN_TO_FORMAT.get(col.get("std_pattern_match") or "")
            if fmt:
                custom_props.append({"property": "testgen.format", "value": fmt})
            # Store the raw pii_flag so it round-trips exactly on import
            if col.get("pii_flag"):
                custom_props.append({"property": "testgen.pii_flag", "value": col["pii_flag"]})
            # Column-level governance tags
            for _tag in _TAG_FIELDS:
                if col.get(_tag):
                    custom_props.append({"property": f"testgen.{_tag}", "value": col[_tag]})
            if custom_props:
                prop["customProperties"] = custom_props

            # examples from top_freq_values — omitted for PII columns to avoid leaking sensitive data
            # DB format: "| value | count\n| value | count\n..." — value is at index 1 after split on "|"
            if col.get("top_freq_values") and not col.get("pii_flag"):
                raw = col["top_freq_values"]
                parts = [p.split("|") for p in raw.split("\n") if "|" in p]
                examples = [v for p in parts if len(p) >= 2 and (v := p[1].strip())][:5]
                if len(examples) >= 2:
                    prop["examples"] = examples

            # strip None values
            prop = {k: v for k, v in prop.items() if v is not None and v != "" and (v is not False or k in ("required", "criticalDataElement"))}
            properties.append(prop)

        result.append({
            "name": table_name,
            "physicalType": "table",
            "properties": properties,
        })
    return result


def _build_references(tests: list[dict]) -> list[dict]:
    refs = []
    for t in tests:
        if t.get("test_scope") == "referential" and t.get("match_table_name"):
            from_cols = [c.strip() for c in (t.get("column_name") or "").split(",") if c.strip()]
            to_cols   = [c.strip() for c in (t.get("match_column_names") or "").split(",") if c.strip()]
            if from_cols and to_cols:
                refs.append({
                    "from": f"{t['table_name']}.{from_cols[0]}" if len(from_cols) == 1 else [f"{t['table_name']}.{c}" for c in from_cols],
                    "to":   f"{t['match_table_name']}.{to_cols[0]}" if len(to_cols) == 1 else [f"{t['match_table_name']}.{c}" for c in to_cols],
                    "type": "foreignKey",
                })
    return refs


def _build_quality(tests: list[dict]) -> list[dict]:
    rules = []
    for t in tests:
        if t.get("test_scope") == "referential":
            continue  # referential tests go into references, not quality

        odcs_meta = _TEST_TYPE_ODCS.get(t["test_type"], _TEST_TYPE_ODCS_DEFAULT)
        origin     = _derive_origin(t.get("last_auto_gen_date"), t.get("last_manual_update"), t.get("lock_refresh"), t["test_type"])
        dimension  = _DQ_DIMENSION_MAP.get(t.get("dq_dimension") or "", "accuracy")
        threshold  = _safe_float(t.get("threshold_value"))
        lower      = _safe_float(t.get("lower_tolerance"))
        upper      = _safe_float(t.get("upper_tolerance"))

        # Decide operator — tolerance band overrides single threshold
        if lower is not None and upper is not None:
            operator = "mustBeBetween"
        else:
            operator = odcs_meta.get("operator", "mustBeLessOrEqualTo")

        # Build description: type description + optional user notes
        type_desc  = (t.get("type_description") or "").strip()
        user_desc  = (t.get("user_description") or "").strip()
        if type_desc and user_desc:
            description: str | None = f"{type_desc} — {user_desc}"
        else:
            description = type_desc or user_desc or None

        rule: dict[str, Any] = {
            "id": str(t["id"]),
            "suiteId": str(t["suite_id"]),
            "name": _nonempty(t.get("user_description")) or t.get("test_name_short") or t["test_type"],
            "description": description,
            "documentationUrl": _TEST_TYPE_DOCS_URL.get(t["test_type"]),
            "type": odcs_meta["odcs_type"],
            "dimension": dimension,
            "unit": odcs_meta.get("unit", "rows"),
            "severity": t.get("severity") or "error",
            "origin": origin,
        }

        # Scope target
        if t.get("column_name"):
            rule["element"] = f"{t['table_name']}.{t['column_name']}"
        elif t.get("table_name"):
            rule["element"] = t["table_name"]

        # Metric (library type)
        if odcs_meta.get("metric"):
            rule["metric"] = odcs_meta["metric"]

        # Threshold / tolerance
        if lower is not None and upper is not None:
            rule[operator] = [lower, upper]
        elif threshold is not None:
            rule[operator] = threshold

        # Custom SQL
        if t["test_type"] == "CUSTOM" and t.get("custom_query"):
            rule["query"] = t["custom_query"]
            rule["mustBeLessOrEqualTo"] = float(t.get("skip_errors") or 0)

        # Vendor metadata for custom type
        if odcs_meta["odcs_type"] == "custom":
            rule["vendor"] = "testgen"
            rule["testType"] = t["test_type"]

        # Filters
        if t.get("subset_condition"):
            rule["filter"] = t["subset_condition"]

        # Last result
        if t.get("result_status"):
            rule["lastResult"] = {
                "status": _result_status_to_odcs(t["result_status"]),
                "measuredValue": _nonempty(t.get("result_measure")),
                "executedAt": t["result_time"].isoformat() if t.get("result_time") else None,
                "message": _nonempty(t.get("result_message")),
            }
            rule["lastResult"] = {k: v for k, v in rule["lastResult"].items() if v is not None}

        rules.append({k: v for k, v in rule.items() if v is not None})
    return rules


def _build_sla(ctx: dict) -> list[dict]:
    sla = []
    if ctx.get("profiling_delay_days"):
        sla.append({
            "property": "latency",
            "value": ctx["profiling_delay_days"],
            "unit": "day",
            "description": "Maximum acceptable age of data before a freshness violation is raised",
        })
    dq_score = _safe_float(ctx.get("last_run_dq_score"))
    if dq_score is not None:
        sla.append({
            "property": "errorRate",
            "value": round(1.0 - dq_score, 4),
            "description": "Observed test failure rate from last test run",
        })
    return sla


def _build_servers(ctx: dict) -> list[dict]:
    flavor_to_odcs = {
        "postgresql": "PostgreSQL",
        "snowflake":  "Snowflake",
        "bigquery":   "BigQuery",
        "mssql":      "SQLServer",
        "redshift":   "Redshift",
        "databricks": "Databricks",
        "trino":      "Trino",
        "oracle":     "Oracle",
    }
    server_type = flavor_to_odcs.get(ctx.get("sql_flavor_code") or "", ctx.get("sql_flavor_code") or "unknown")
    entry: dict[str, Any] = {
        "server": ctx.get("table_group_schema") or ctx.get("project_db") or "default",
        "type": server_type,
        "host": _nonempty(ctx.get("project_host")),
        "port": ctx.get("project_port"),
        "database": _nonempty(ctx.get("project_db")),
        "schema": _nonempty(ctx.get("table_group_schema")),
    }
    return [{k: v for k, v in entry.items() if v is not None}]


def _build_compliance_summary(tests: list[dict]) -> dict:
    by_dimension: dict[str, str] = {}
    violated: list[dict] = []
    priority = ["error", "failing", "warning", "passing"]

    for t in tests:
        status = _result_status_to_odcs(t.get("result_status"))
        if not status:
            continue
        dim = _DQ_DIMENSION_MAP.get(t.get("dq_dimension") or "", "accuracy")
        current = by_dimension.get(dim)
        if current is None or priority.index(status) < priority.index(current):
            by_dimension[dim] = status
        if status in ("error", "failing", "warning"):
            violated.append({
                "testId": str(t["id"]),
                "name": _nonempty(t.get("user_description")) or t.get("test_name_short") or t["test_type"],
                "element": f"{t.get('table_name', '')}.{t.get('column_name', '')}".strip(".") or None,
                "status": status,
                "severity": t.get("severity") or "error",
                "message": _nonempty(t.get("result_message")),
            })

    if not by_dimension:
        return {}

    overall = "passing"
    for s in by_dimension.values():
        if priority.index(s) < priority.index(overall):
            overall = s

    result: dict[str, Any] = {"overall": overall}
    if by_dimension:
        result["byDimension"] = by_dimension
    if violated:
        result["violatedTests"] = [{k: v for k, v in v.items() if v is not None} for v in violated]
    return result


# ---------------------------------------------------------------------------
# YAML annotation
# ---------------------------------------------------------------------------

_SECTION_COMMENTS: dict[str, str] = {
    "servers:":          "# ── Connection & Server ──────────────────────────────────────────────",
    "schema:":           "# ── Schema — DDL + profiling terms (tables, columns, types) ────────────",
    "references:":       "# ── References — referential integrity (foreign keys) ──────────────────",
    "quality:":          "# ── Quality rules — test terms (active test definitions) ────────────────",
    "slaProperties:":    "# ── SLA Properties ───────────────────────────────────────────────────",
    "testRunHistory:":   "# ── Test Run History — last 5 completed runs ──────────────────────────",
    "compliance:":       "# ── Compliance Summary ───────────────────────────────────────────────",
    "customProperties:": "# ── Custom & Vendor Properties ───────────────────────────────────────",
    "team:":             "# ── Team ─────────────────────────────────────────────────────────────",
    "description:":      "# ── Description ──────────────────────────────────────────────────────",
}


def _build_test_run_history(runs: list[dict]) -> list[dict]:
    """Convert raw test_runs rows to a compact ODCS-friendly history list."""
    history = []
    for r in runs:
        entry: dict[str, Any] = {
            "executedAt": r["test_starttime"].isoformat() if r.get("test_starttime") else None,
            "suite": _nonempty(r.get("suite_name")),
            "testCount": r.get("test_ct"),
            "passed": r.get("passed_ct"),
            "failed": r.get("failed_ct"),
            "warning": r.get("warning_ct"),
            "dqScore": round(float(r["dq_score_test_run"]), 4) if r.get("dq_score_test_run") is not None else None,
        }
        history.append({k: v for k, v in entry.items() if v is not None})
    return history


def _annotate_yaml(yaml_str: str) -> str:
    """Insert readable section-divider comments before top-level YAML keys."""
    header = (
        "# ODCS v3.1.0 Data Contract\n"
        "# Open Data Contract Standard — https://bitol-io.github.io/open-data-contract-standard/v3.1.0/\n"
        "# Generated by TestGen\n"
        "#\n"
    )
    lines = yaml_str.splitlines()
    result: list[str] = []
    for line in lines:
        if not line.startswith(" ") and not line.startswith("\t") and not line.startswith("#") and ":" in line:
            key = line.split(":")[0].strip() + ":"
            if key in _SECTION_COMMENTS:
                result.append("")
                result.append(_SECTION_COMMENTS[key])
        result.append(line)
    return header + "\n".join(result)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

@with_database_session
def run_export_data_contract(
    table_group_id: str,
    output_path: str | None = None,
    output_stream: io.StringIO | None = None,
) -> None:
    schema = get_tg_schema()

    ctx = _fetch_group_context(table_group_id, schema)
    if not ctx:
        LOG.error("Table group not found: %s", table_group_id)
        sys.exit(1)

    columns     = _fetch_columns(table_group_id, schema)
    suite_scope = _fetch_suite_scope(table_group_id, schema)
    tests       = _fetch_tests(table_group_id, schema)
    run_history = _fetch_test_run_history(table_group_id, schema)

    if suite_scope["total"] > 0 and not suite_scope["included"]:
        LOG.warning(
            "No test suites are marked include_in_contract=True for table group %s — "
            "quality section will be empty.",
            table_group_id,
        )

    status = (ctx.get("contract_status") or "draft").lower()
    if status not in VALID_STATUSES:
        status = "draft"

    contract: dict[str, Any] = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": str(ctx["table_group_id"]),
        "version": ctx.get("contract_version") or "1.0.0",
        "status": status,
        "name": ctx["table_groups_name"],
        "tenant": ctx.get("project_code"),
        "domain": _nonempty(ctx.get("business_domain")),
        "dataProduct": _nonempty(ctx.get("data_product")),
        "tags": [t for t in [ctx.get("data_source"), ctx.get("transform_level")] if t],
    }

    if ctx.get("group_description") or ctx.get("source_system"):
        contract["description"] = {k: v for k, v in {
            "purpose": _nonempty(ctx.get("group_description")),
            "limitations": None,
            "usage": None,
        }.items() if v}

    if ctx.get("last_run_at"):
        failed  = int(ctx.get("last_run_failed_ct") or 0)
        warning = int(ctx.get("last_run_warning_ct") or 0)
        error   = int(ctx.get("last_run_error_ct") or 0)
        if error > 0:
            run_status = "error"
        elif failed > 0:
            run_status = "failing"
        elif warning > 0:
            run_status = "warning"
        else:
            run_status = "passing"
        contract["lastRunAt"]     = ctx["last_run_at"].isoformat()
        contract["lastRunStatus"] = run_status

    contract["servers"] = _build_servers(ctx)

    schema_section = _build_schema(columns)
    if schema_section:
        contract["schema"] = schema_section

    refs = _build_references(tests)
    if refs:
        contract["references"] = refs

    quality = _build_quality(tests)
    if quality:
        contract["quality"] = quality

    sla = _build_sla(ctx)
    if sla:
        contract["slaProperties"] = sla

    history = _build_test_run_history(run_history)
    if history:
        contract["testRunHistory"] = history

    if ctx.get("stakeholder_group"):
        contract["team"] = {
            "name": ctx["stakeholder_group"],
            "members": [],
        }

    compliance = _build_compliance_summary(tests)
    if compliance:
        contract["compliance"] = compliance

    # x-testgen: auditable extension block — not part of the ODCS spec
    x_testgen: dict[str, Any] = {
        "includedSuites": suite_scope["included"],
    }
    if suite_scope["excluded"]:
        x_testgen["excludedSuites"] = suite_scope["excluded"]
    contract["x-testgen"] = x_testgen

    contract["customProperties"] = [p for p in [
        {"property": "sourceSystem",  "value": ctx["source_system"]}  if ctx.get("source_system")  else None,
        {"property": "sourceProcess", "value": ctx["source_process"]} if ctx.get("source_process") else None,
        {"property": "dataLocation",  "value": ctx["data_location"]}  if ctx.get("data_location")  else None,
        {"property": "transformLevel","value": ctx["transform_level"]} if ctx.get("transform_level") else None,
        {"property": "exportedAt",    "value": datetime.now(UTC).isoformat()},
    ] if p]

    # Strip top-level None / empty list values
    contract = {k: v for k, v in contract.items() if v is not None and v != [] and v != {}}

    output = yaml.dump(contract, default_flow_style=False, allow_unicode=True, sort_keys=False)
    output = _annotate_yaml(output)

    if output_path:
        with open(output_path, "w") as fh:
            fh.write(output)
        LOG.info("Data contract written to %s", output_path)
    elif output_stream is not None:
        output_stream.write(output)
    else:
        sys.stdout.write(output)
