"""
Data Contract — props builder and pure coverage/term helpers.

No Streamlit, no direct DB calls.  _build_contract_props accepts an optional
``gov_by_col`` dict so callers (and tests) can supply pre-fetched governance
data instead of triggering a DB round-trip inside this module.
"""
from __future__ import annotations

import html
import re

from testgen.ui.queries.data_contract_queries import _fetch_governance_data

# ---------------------------------------------------------------------------
# Shared constants — imported by data_contract_dialogs.py as well
# ---------------------------------------------------------------------------

_STATUS_ICON: dict[str, str] = {
    "passing": "✅",
    "warning": "⚠️",
    "failing": "❌",
    "error":   "🔴",
    "not run": "⏳",
}

_TIERS: dict[str, tuple[str, str, str]] = {
    "db_enforced": ("🏛️", "Database Schema Enforced",
                    "The database DDL itself rejects violations at write time — no test needed"),
    "tested":      ("⚡", "Tested",
                    "An active quality test checks this on every test run — hard pass/fail result"),
    "monitor":     ("📡", "Monitor",
                    "A continuous monitor (Freshness, Volume, Schema, or Metric) watches this column for anomalies over time"),
    "monitored":   ("📡", "Monitored",
                    "A continuous monitor (Freshness, Volume, Schema, or Metric) watches this element for anomalies over time"),
    "observed":    ("📸", "Observed",
                    "Captured from profiling statistics — a snapshot of what we saw, not what we're watching"),
    "declared":    ("🏷️", "Declared",
                    "Manually annotated governance metadata — not derived from or checked against the data"),
}

# Test types that originate from the monitor suite — displayed as "Monitor" not "Test"
_MONITOR_TEST_TYPES: frozenset[str] = frozenset({
    "Freshness_Trend", "Volume_Trend", "Schema_Drift", "Metric_Trend",
})

_CHAR_CONSTRAINED_RE = re.compile(
    r"^(varchar|character varying|char|nchar|nvarchar|bpchar|string)\s*\(\d+\)",
    re.IGNORECASE,
)
_NUMERIC_PREC_RE = re.compile(
    r"^(numeric|decimal|number)\s*\(\d+\s*,\s*\d+\)",
    re.IGNORECASE,
)
_INTEGER_TYPES: frozenset[str] = frozenset({
    "integer", "int", "int2", "int4", "int8", "int16", "int32", "int64",
    "bigint", "smallint", "tinyint", "mediumint",
})
_DB_TYPED: frozenset[str] = frozenset({
    "boolean", "bool", "date", "timestamp", "timestamptz",
    "timestamp with time zone", "timestamp without time zone",
    "time", "timetz", "float", "float4", "float8", "double precision",
    "real", "bytea", "binary", "varbinary", "blob",
})

_SOURCE_META: dict[str, tuple[str, str, str]] = {
    "ddl":        ("DDL",        "#f3f0fa", "#7c4dff"),
    "profiling":  ("Profiling",  "#e8f4fd", "#1976d2"),
    "governance": ("Governance", "#fffde7", "#ffa000"),
    "test":       ("Test",       "#f1f8e9", "#388e3c"),
    "monitor":    ("Monitor",    "#e8f5e9", "#00695c"),
}

_VERIF_META: dict[str, tuple[str, str, str]] = {
    "db_enforced": ("🏛️", "DB Enforced", "#283593"),
    "tested":      ("⚡", "Tested",       "#1b5e20"),
    "monitor":     ("📡", "Monitor",      "#00695c"),
    "monitored":   ("📡", "Monitored",    "#00695c"),
    "observed":    ("📸", "Observed",     "#546e7a"),
    "declared":    ("🏷️", "Declared",     "#795548"),
}

# Governance fields sourced directly from data_column_chars
_GOV_FIELDS: list[tuple[str, str]] = [
    ("Critical Data Element", "critical_data_element"),
    ("Excluded Data Element", "excluded_data_element"),
    ("PII",                   "pii_flag"),
    ("Description",           "description"),
    ("Data Source",           "data_source"),
    ("Source System",         "source_system"),
    ("Source Process",        "source_process"),
    ("Business Domain",       "business_domain"),
    ("Stakeholder Group",     "stakeholder_group"),
    ("Transform Level",       "transform_level"),
    ("Aggregation Level",     "aggregation_level"),
    ("Data Product",          "data_product"),
]


# ---------------------------------------------------------------------------
# YAML compat helper — reads profiling/constraint opts from either format
# ---------------------------------------------------------------------------

def _prop_opts(prop: dict) -> dict:
    """Return a flat dict of profiling/constraint option values for a YAML property.

    Supports both the legacy ``logicalTypeOptions`` dict (pre-ODCS migration) and
    the current ``customProperties`` list (ODCS-compliant, ``testgen.*`` keys).
    The returned keys are always the short form (e.g. ``"minimum"``, ``"primaryKey"``).
    """
    if "customProperties" in prop:
        return {
            cp["property"].removeprefix("testgen."): cp["value"]
            for cp in (prop["customProperties"] or [])
            if isinstance(cp.get("property"), str) and cp["property"].startswith("testgen.")
        }
    return prop.get("logicalTypeOptions") or {}


# ---------------------------------------------------------------------------
# Coverage tier helpers
# ---------------------------------------------------------------------------

def _column_coverage_tiers(prop: dict, all_quality_rules: list[dict]) -> list[str]:
    physical       = (prop.get("physicalType") or "").strip()
    physical_lower = physical.lower()
    base           = physical_lower.split("(")[0].strip()
    opts           = _prop_opts(prop)
    col_name       = prop.get("name", "")
    tiers: list[str] = []

    if (
        _CHAR_CONSTRAINED_RE.match(physical_lower)
        or _NUMERIC_PREC_RE.match(physical_lower)
        or base in _INTEGER_TYPES
        or base in _DB_TYPED
        or re.search(r"\(\d+\)", physical_lower)
    ):
        tiers.append("db_enforced")

    if col_name and any(
        r.get("element", "").split(".")[-1] == col_name
        for r in all_quality_rules
    ):
        tiers.append("tested")

    if (
        _CHAR_CONSTRAINED_RE.match(physical_lower)
        or _NUMERIC_PREC_RE.match(physical_lower)
        or base in _INTEGER_TYPES
    ):
        tiers.append("monitored")

    if (
        opts.get("minimum") is not None
        or opts.get("maximum") is not None
        or opts.get("minLength") is not None
        or opts.get("maxLength") is not None
        or prop.get("logicalType")
        or prop.get("examples")
        or (opts.get("format") and "tested" not in tiers)
    ):
        tiers.append("observed")

    if prop.get("classification") or prop.get("criticalDataElement") or prop.get("description"):
        tiers.append("declared")

    return tiers or ["observed"]


def _tier_badge(tiers: list[str]) -> str:
    return "".join(_TIERS[t][0] for t in tiers if t in _TIERS)


# ---------------------------------------------------------------------------
# Coverage helper — single definition used by health stats and per-column props
# ---------------------------------------------------------------------------

def _is_covered(prop: dict, col_rules: list[dict]) -> bool:
    """A column is 'covered' when it has at least one non-schema term."""
    return bool(
        prop.get("classification")
        or prop.get("criticalDataElement")
        or prop.get("description")
        or _prop_opts(prop).get("format")
        or col_rules
    )


# ---------------------------------------------------------------------------
# Enforcement-tier classification (replaces binary _is_covered for health/matrix)
# ---------------------------------------------------------------------------

def _has_meaningful_ddl_constraint(prop: dict, col_refs: list[dict] | None = None) -> bool:
    """True when the column has a meaningful DDL constraint beyond bare data type.

    Meaningful = NOT NULL, PK, FK, char-constrained (VARCHAR(n)), numeric precision.
    Bare INTEGER, BOOLEAN, TEXT, TIMESTAMP etc. without additional constraints = False.
    """
    if prop.get("required") or prop.get("nullable") is False:
        return True
    opts = _prop_opts(prop)
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
    """True when the column has observed stats or declared metadata (but no tests/DDL)."""
    opts = _prop_opts(prop)
    gov = gov_col or {}
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
    """Assign the highest enforcement tier to a column/element.

    Returns one of: "tg" | "db" | "unf" | "none".
    """
    if col_rules:
        return "tg"
    if _has_meaningful_ddl_constraint(prop, col_refs):
        return "db"
    if _has_unenforced_terms(prop, gov_col):
        return "unf"
    return "none"


# ---------------------------------------------------------------------------
# Term helpers
# ---------------------------------------------------------------------------

def _format_pii_flag(pii_flag: str) -> str:  # noqa: ARG001
    """Any non-empty pii_flag value means the column is PII."""
    return "Yes"


def _term(name: str, value: object, source: str, verif: str, **meta: object) -> dict:
    return {"name": name, "value": str(value), "source": source, "verif": verif, **meta}


def _term_card_html(term: dict) -> str:
    """Static term rendered as HTML card: left-border stripe + single verification badge."""
    src_key  = term["source"]
    verif_key = term["verif"]
    src_label, src_bg, border_color = _SOURCE_META.get(src_key, ("?", "#f5f5f5", "#999"))
    verif_icon, verif_label, badge_color = _VERIF_META.get(verif_key, ("", verif_key, "#666"))
    name_esc = html.escape(term["name"], quote=True)
    val_esc  = html.escape(term["value"], quote=True)
    return (
        f'<div style="border:1px solid #e0e0e0;border-left:4px solid {border_color};'
        f'border-radius:0 6px 6px 0;padding:7px 10px;'
        f'background:{src_bg};min-width:120px;max-width:210px;flex:0 0 auto;">'
        f'<div style="font-size:10px;color:#888;text-transform:uppercase;'
        f'letter-spacing:0.5px;margin-bottom:2px;">{src_label} · {name_esc}</div>'
        f'<div style="font-size:13px;font-weight:600;color:#1a1a1a;'
        f'word-break:break-word;margin-bottom:5px;">{val_esc}</div>'
        f'<span style="font-size:10px;background:{badge_color};color:#fff;'
        f'border-radius:3px;padding:1px 5px;">{verif_icon} {verif_label}</span>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Lookup builder
# ---------------------------------------------------------------------------

def _build_lookups(
    quality: list[dict],
    references: list[dict],
    anomalies: list[dict],
) -> tuple[dict, dict, dict]:
    rules_by_element: dict[str, list[dict]] = {}
    for rule in quality:
        elem = rule.get("element", "")
        rules_by_element.setdefault(elem, []).append(rule)

    anomalies_by_col: dict[tuple[str, str], list[dict]] = {}
    for a in anomalies:
        key = (a.get("table_name", ""), a.get("column_name", ""))
        anomalies_by_col.setdefault(key, []).append(a)

    refs_by_col: dict[str, list[dict]] = {}
    for ref in references:
        col = ref.get("from", "")
        refs_by_col.setdefault(col, []).append(ref)

    return rules_by_element, anomalies_by_col, refs_by_col


# ---------------------------------------------------------------------------
# Column term extractor
# ---------------------------------------------------------------------------

def _extract_column_terms(
    prop: dict,
    col_rules: list[dict],
    col_anomalies: list[dict],
    col_refs: list[dict],
    gov: dict | None = None,
) -> list[dict]:
    """Build all terms for a single column.

    gov — live governance dict from data_column_chars (keyed by db column name).
    When provided it replaces the YAML-derived governance fields.
    """
    terms: list[dict] = []
    opts           = _prop_opts(prop)
    physical       = (prop.get("physicalType") or "").strip()
    physical_lower = physical.lower()
    base           = physical_lower.split("(")[0].strip()

    # --- Schema terms (DDL) ---
    if physical:
        db_enforced = bool(
            _CHAR_CONSTRAINED_RE.match(physical_lower)
            or _NUMERIC_PREC_RE.match(physical_lower)
            or base in _INTEGER_TYPES
            or base in _DB_TYPED
        )
        terms.append(_term("Data Type", physical, "ddl",
                            "db_enforced" if db_enforced else "observed", kind="static"))

    if prop.get("required") or prop.get("nullable") is False:
        terms.append(_term("Not Null", "Required", "ddl", "db_enforced", kind="static"))

    if opts.get("primaryKey"):
        terms.append(_term("Primary Key", "Yes", "ddl", "db_enforced", kind="static"))

    for ref in col_refs:
        terms.append(_term("Foreign Key", f"→ {ref.get('to', '')}", "ddl", "db_enforced", kind="static"))

    # --- Governance terms (live from data_column_chars) ---
    if gov:
        if gov.get("critical_data_element"):
            terms.append(_term("Critical Data Element", "Yes", "governance", "declared", kind="static"))
        if gov.get("excluded_data_element"):
            terms.append(_term("Excluded Data Element", "Yes", "governance", "declared", kind="static"))
        pii = gov.get("pii_flag")
        if pii:
            terms.append(_term("PII", _format_pii_flag(pii), "governance", "declared", kind="static"))
        desc = gov.get("description") or ""
        if desc:
            short = desc if len(desc) <= 45 else desc[:42] + "…"
            terms.append(_term("Description", short, "governance", "declared", kind="static", full_value=desc))
        for label, col_key in _GOV_FIELDS:
            if col_key in ("critical_data_element", "excluded_data_element", "pii_flag", "description"):
                continue
            val = gov.get(col_key) or ""
            if val:
                terms.append(_term(label, val, "governance", "declared", kind="static"))
    else:
        # Fallback: use YAML-derived governance fields (legacy path)
        if prop.get("criticalDataElement"):
            terms.append(_term("Critical Data Element", "Yes", "governance", "declared", kind="static"))
        if prop.get("description"):
            full_desc  = str(prop["description"])
            desc_short = full_desc if len(full_desc) <= 45 else full_desc[:42] + "…"
            terms.append(_term("Description", desc_short, "governance", "declared", kind="static",
                                full_value=full_desc))

    # --- Profiling observations ---
    if opts.get("minimum") is not None:
        terms.append(_term("Min Value",   opts["minimum"],   "profiling", "observed", kind="static"))
    if opts.get("maximum") is not None:
        terms.append(_term("Max Value",   opts["maximum"],   "profiling", "observed", kind="static"))
    if opts.get("minLength") is not None:
        terms.append(_term("Min Length",  opts["minLength"], "profiling", "observed", kind="static"))
    if opts.get("maxLength") is not None:
        terms.append(_term("Max Length",  opts["maxLength"], "profiling", "observed", kind="static"))
    if opts.get("format"):
        terms.append(_term("Format",      opts["format"],    "profiling", "observed", kind="static"))
    if prop.get("logicalType"):
        terms.append(_term("Logical Type", prop["logicalType"], "profiling", "observed", kind="static"))

    # --- Live terms (tests + monitors) ---
    for rule in col_rules:
        test_name      = rule.get("name") or rule.get("type") or rule.get("testType") or "Test"
        test_type      = rule.get("testType", "")
        is_monitor_rule = test_type in _MONITOR_TEST_TYPES
        last           = rule.get("lastResult") or {}
        status         = last.get("status") or "not run"
        status_icon    = _STATUS_ICON.get(status, "⏳")
        if is_monitor_rule:
            terms.append(_term(
                "Monitor", f"{status_icon} {test_name}",
                "monitor", "monitored",
                kind="live", rule=rule, status=status,
            ))
        else:
            terms.append(_term(
                "Test", f"{status_icon} {test_name}",
                "test", "tested",
                kind="live", rule=rule, status=status,
            ))

    for anomaly in col_anomalies:
        likelihood      = anomaly.get("issue_likelihood", "")
        aname           = anomaly.get("anomaly_name", "")
        likelihood_icon = {"Definite": "❌", "Likely": "⚠️", "Possible": "🔵"}.get(likelihood, "⚠️")
        terms.append(_term(
            "Hygiene", f"{likelihood_icon} {aname}",
            "profiling", "observed",
            kind="live", anomaly=anomaly,
        ))

    return terms


# ---------------------------------------------------------------------------
# Quality status helpers
# ---------------------------------------------------------------------------

def _quality_counts(rules: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rules:
        s = (r.get("lastResult") or {}).get("status") or "not run"
        counts[s] = counts.get(s, 0) + 1
    return counts


def _worst_status(counts: dict[str, int]) -> str:
    priority = ["error", "failing", "warning", "passing", "not run"]
    worst = "not run"
    for s in counts:
        if s in priority and priority.index(s) < priority.index(worst):
            worst = s
    return worst


# ---------------------------------------------------------------------------
# Main props builder
# ---------------------------------------------------------------------------

def _build_contract_props(
    table_group: object,
    doc: dict,
    anomalies: list[dict],
    contract_yaml: str,
    run_dates: dict | None = None,
    suite_scope: dict | None = None,
    test_statuses: dict[str, str] | None = None,
    gov_by_col: dict | None = None,
) -> dict:
    """Pre-compute all display data for the VanJS component.

    gov_by_col — optional pre-fetched governance map keyed by (table_name, col_name).
    When None the function fetches it from the DB using _fetch_governance_data.
    """
    schema: list[dict]    = doc.get("schema") or []
    quality: list[dict]   = doc.get("quality") or []
    references: list[dict] = doc.get("references") or []

    # Inject fresh test statuses — overrides whatever was cached in the YAML
    if test_statuses:
        for rule in quality:
            rule_id = rule.get("id", "")
            if rule_id in test_statuses:
                rule.setdefault("lastResult", {})["status"] = test_statuses[rule_id]

    # ── Meta ──────────────────────────────────────────────────────────────────
    description = doc.get("description") or {}
    description_purpose = (
        description.get("purpose") if isinstance(description, dict) else str(description)
    ) or ""

    meta = {
        "description_purpose": description_purpose,
        "project_code":        getattr(table_group, "project_code", ""),
        "table_group_id":      str(getattr(table_group, "id", "") or ""),
    }

    # ── Health ────────────────────────────────────────────────────────────────
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

    _n_elements = n_cols + len(schema)

    counts = _quality_counts(quality)
    rd = run_dates or {}

    def _fmt_ts(ts: object) -> str:
        if ts is None:
            return ""
        import datetime
        if isinstance(ts, (datetime.datetime, datetime.date)):
            return ts.strftime("%Y-%m-%d %H:%M")
        return str(ts)[:16]

    _scope = suite_scope or {}
    health = {
        "coverage_pct":          coverage_pct,
        "covered":               covered,
        "n_cols":                n_cols,
        "tg_enforced":           0,
        "db_enforced":           0,
        "unenforced":            0,
        "uncovered":             0,
        "n_elements":            _n_elements,
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

    # ── Governance metadata (live from data_column_chars) ─────────────────────
    table_group_id_str = str(getattr(table_group, "id", "") or "")
    effective_gov = gov_by_col if gov_by_col is not None else _fetch_governance_data(table_group_id_str)

    # ── Coverage matrix rows ──────────────────────────────────────────────────
    rules_by_element_full, anomalies_by_col, refs_by_col = _build_lookups(quality, references, anomalies)
    matrix_rows: list[dict] = []
    for table in schema:
        table_name   = table.get("name", "")
        tbl_rules_mx = rules_by_element_full.get(table_name, [])
        # Always emit the table-level row (even when no table-level rules exist)
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
        for prop in (table.get("properties") or []):
            col_name    = prop.get("name", "")
            col_key     = f"{table_name}.{col_name}"
            opts        = _prop_opts(prop)
            col_rules   = rules_by_element_full.get(col_key, []) + rules_by_element_full.get(col_name, [])
            col_anomalies = anomalies_by_col.get((table_name, col_name), [])
            col_refs    = refs_by_col.get(col_key, []) + refs_by_col.get(col_name, [])
            physical       = (prop.get("physicalType") or "").strip()
            physical_lower = physical.lower()
            base_type      = physical_lower.split("(")[0].strip()
            is_db_typed    = bool(physical and (
                _CHAR_CONSTRAINED_RE.match(physical_lower)
                or _NUMERIC_PREC_RE.match(physical_lower)
                or base_type in _INTEGER_TYPES
                or base_type in _DB_TYPED
            ))
            db_ct = sum([
                1 if is_db_typed else 0,
                1 if (prop.get("required") or prop.get("nullable") is False) else 0,
                1 if opts.get("primaryKey") else 0,
                len(col_refs),
            ])
            tested_ct = sum(1 for r in col_rules if r.get("testType", "") not in _MONITOR_TEST_TYPES)
            mon_ct    = sum(1 for r in col_rules if r.get("testType", "") in _MONITOR_TEST_TYPES)
            obs_ct    = sum([
                1 if (physical and not is_db_typed) else 0,
                1 if opts.get("minimum") is not None else 0,
                1 if opts.get("maximum") is not None else 0,
                1 if opts.get("minLength") is not None else 0,
                1 if opts.get("maxLength") is not None else 0,
                1 if opts.get("format") else 0,
                1 if prop.get("logicalType") else 0,
                len(col_anomalies),
            ])
            gov_col = effective_gov.get((table_name, col_name)) or {}
            decl_ct = sum([
                1 if (gov_col.get("description") or prop.get("description")) else 0,
                1 if (gov_col.get("pii_flag") or prop.get("classification")) else 0,
                1 if (gov_col.get("critical_data_element") or prop.get("criticalDataElement")) else 0,
                sum(1 for _, db_col in _GOV_FIELDS
                    if db_col not in ("description", "pii_flag", "critical_data_element",
                                      "excluded_data_element")
                    and gov_col.get(db_col)),
            ])
            matrix_rows.append({
                "table":  table_name,
                "column": col_name,
                "db":     db_ct,
                "tested": tested_ct,
                "mon":    mon_ct,
                "obs":    obs_ct,
                "decl":   decl_ct,
                "tier":   _classify_enforcement_tier(prop, col_rules, gov_col=gov_col, col_refs=col_refs),
            })

    # ── Tier counts from matrix rows (matches JS pill logic exactly) ─────────
    _tier_tg = _tier_db = _tier_unf = _tier_none = 0
    for _row in matrix_rows:
        _has_tg  = (_row["tested"] + _row["mon"]) > 0
        _has_db  = _row["db"] > 0
        _has_unf = (_row["obs"] + _row["decl"]) > 0
        if _has_tg:  _tier_tg  += 1
        if _has_db:  _tier_db  += 1
        if _has_unf: _tier_unf += 1
        if not _has_tg and not _has_db and not _has_unf:
            _tier_none += 1
    health["tg_enforced"] = _tier_tg
    health["db_enforced"] = _tier_db
    health["unenforced"]  = _tier_unf
    health["uncovered"]   = _tier_none

    # ── Gap analysis ──────────────────────────────────────────────────────────
    gap_items: list[dict] = []
    for table in schema:
        table_name     = table.get("name", "")
        table_has_tests = False
        for prop in (table.get("properties") or []):
            col_name  = prop.get("name", "")
            col_key   = f"{table_name}.{col_name}"
            col_rules = rules_by_element_full.get(col_key, []) + rules_by_element_full.get(col_name, [])
            opts      = _prop_opts(prop)
            if col_rules:
                table_has_tests = True
            cls = (prop.get("classification") or "").lower()
            if cls in ("pii", "sensitive", "restricted") and not col_rules:
                gap_items.append({"table": table_name, "msg": f"`{col_name}` classified **{prop['classification']}** but has no quality test", "severity": "error"})
            if prop.get("criticalDataElement") and not col_rules:
                gap_items.append({"table": table_name, "msg": f"`{col_name}` is a **Critical Data Element** with no test enforcing it", "severity": "warning"})
            has_range = opts.get("minimum") is not None or opts.get("maximum") is not None
            range_ops = ("mustBe", "mustBeGreaterThan", "mustBeGreaterOrEqualTo",
                         "mustBeLessThan", "mustBeLessOrEqualTo", "mustBeBetween")
            has_range_test = any(op in r for r in col_rules for op in range_ops)
            if has_range and not has_range_test:
                gap_items.append({"table": table_name, "msg": f"`{col_name}` has observed min/max but no range test is configured", "severity": "info"})
            if not prop.get("description"):
                gap_items.append({"table": table_name, "msg": f"`{col_name}` has no description (governance gap)", "severity": "info"})
        if not table_has_tests:
            gap_items.append({"table": table_name, "msg": "Table has no quality tests of any kind", "severity": "warning"})

    errors   = [g["msg"] for g in gap_items if g["severity"] == "error"]
    warnings = [g["msg"] for g in gap_items if g["severity"] == "warning"]
    infos    = [g["msg"] for g in gap_items if g["severity"] == "info"]

    # ── Per-table column terms ────────────────────────────────────────────────
    tables_data: list[dict] = []
    for table in schema:
        table_name = table.get("name", "")
        tbl_rules  = rules_by_element_full.get(table_name, [])
        table_terms: list[dict] = [
            {
                "name":        "Monitor" if r.get("testType", "") in _MONITOR_TEST_TYPES else "Test",
                "value":       r.get("name") or r.get("testType") or "Test",
                "source":      "monitor" if r.get("testType", "") in _MONITOR_TEST_TYPES else "test",
                "verif":       "monitored" if r.get("testType", "") in _MONITOR_TEST_TYPES else "tested",
                "status":      (r.get("lastResult") or {}).get("status") or "not run",
                "rule_id":     str(r.get("id", "") or ""),
                "suite_id":    str(r.get("suiteId", "") or ""),
                "test_name":   r.get("name") or r.get("testType") or "Test",
                "element":     r.get("element") or table_name,
                "dimension":   r.get("dimension") or "",
                "severity":    r.get("severity") or "",
                "executed_at": (r.get("lastResult") or {}).get("executedAt") or "",
            }
            for r in tbl_rules
        ]

        cols_data: list[dict] = []
        for prop in (table.get("properties") or []):
            col_name      = prop.get("name", "")
            col_key       = f"{table_name}.{col_name}"
            col_rules     = rules_by_element_full.get(col_key, []) + rules_by_element_full.get(col_name, [])
            col_anomalies = anomalies_by_col.get((table_name, col_name), [])
            col_refs      = refs_by_col.get(col_key, []) + refs_by_col.get(col_name, [])
            gov           = effective_gov.get((table_name, col_name))
            terms         = _extract_column_terms(prop, col_rules, col_anomalies, col_refs, gov=gov)
            static_terms  = [c for c in terms if c.get("kind") == "static"]
            live_terms    = [c for c in terms if c.get("kind") == "live"]

            worst_live = "clean"
            for c in live_terms:
                s = c.get("status", "")
                if s in ("failing", "error"):
                    worst_live = "failing"
                    break
                if s == "warning" and worst_live != "failing":
                    worst_live = "warning"
                if c.get("name") == "Hygiene" and worst_live == "clean":
                    worst_live = "warning"

            is_cov        = _is_covered(prop, col_rules)
            column_id     = (gov or {}).get("column_id", "")

            cols_data.append({
                "name":         col_name,
                "type":         prop.get("physicalType") or "",
                "is_pk":        bool(_prop_opts(prop).get("primaryKey")),
                "is_fk":        bool(col_refs),
                "column_id":    column_id,
                "covered":      is_cov,
                "status":       worst_live,
                "static_terms": [
                    {"name": c["name"], "value": c["value"], "source": c["source"], "verif": c["verif"]}
                    for c in static_terms
                ],
                "live_terms": [
                    {
                        "name":         c["name"],
                        "value":        c["value"],
                        "source":       c["source"],
                        "verif":        c["verif"],
                        "status":       c.get("status") or "",
                        "rule_id":      str(c.get("rule", {}).get("id", "") or ""),
                        "suite_id":     str(c.get("rule", {}).get("suiteId", "") or ""),
                        "test_name":    (c.get("rule", {}).get("name") or c.get("rule", {}).get("testType") or ""),
                        "test_type":    (c.get("rule", {}).get("type") or c.get("rule", {}).get("testType") or ""),
                        "element":      (c.get("rule", {}).get("element") or ""),
                        "dimension":    (c.get("rule", {}).get("dimension") or ""),
                        "severity":     (c.get("rule", {}).get("severity") or ""),
                        "executed_at":  ((c.get("rule", {}).get("lastResult") or {}).get("executedAt") or ""),
                        "anomaly_type": (c.get("anomaly", {}) or {}).get("anomaly_type", "") if c["name"] == "Hygiene" else "",
                    }
                    for c in live_terms
                ],
            })

        if cols_data or table_terms:
            tables_data.append({
                "name":         table_name,
                "column_count": len(cols_data),
                "table_terms":  table_terms,
                "columns":      cols_data,
            })

    return {
        "table_group_name": getattr(table_group, "table_groups_name", ""),
        "meta":             meta,
        "yaml_content":     contract_yaml,
        "health":           health,
        "suite_scope":      suite_scope or {"included": [], "excluded": [], "total": 0},
        "coverage_matrix":  matrix_rows,
        "gaps":             {"errors": errors, "warnings": warnings, "infos": infos, "items": gap_items},
        "tables":           tables_data,
    }
