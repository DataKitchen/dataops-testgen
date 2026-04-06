"""
Data Contract UI view — ODCS v3.1.0

Health dashboard · Coverage matrix · Gap analysis · Claims detail with inline editing.
"""
from __future__ import annotations

import html
import io
import logging
import re
import typing

_log = logging.getLogger(__name__)
LOG = logging.getLogger("testgen")

import streamlit as st
import yaml

from testgen.commands.contract_staleness import StaleDiff, compute_staleness_diff
from testgen.commands.contract_versions import (
    has_any_version,
    list_contract_versions,
    load_contract_version,
    mark_contract_not_stale,
    save_contract_version,
)
from testgen.commands.export_data_contract import run_export_data_contract
from testgen.commands.import_data_contract import ContractDiff  # re-exported for test compatibility
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import execute_db_queries, fetch_dict_from_db
from testgen.common.models import with_database_session
from testgen.common.models.table_group import TableGroup
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session

PAGE_TITLE = "Data Contract"
PAGE_ICON = "contract"

# Emoji work everywhere (expander titles, dataframe cells, markdown).
# Material icon syntax only works inside st.markdown / st.write.
_STATUS_ICON: dict[str, str] = {
    "passing": "✅",
    "warning": "⚠️",
    "failing": "❌",
    "error":   "🔴",
    "not run": "⏳",
}


# ---------------------------------------------------------------------------
# Five-tier enforcement taxonomy
# ---------------------------------------------------------------------------

# Governance fields sourced directly from data_column_chars
_GOV_FIELDS: list[tuple[str, str]] = [
    # (claim label, db column name)
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


def _column_coverage_tiers(prop: dict, all_quality_rules: list[dict]) -> list[str]:
    physical = (prop.get("physicalType") or "").strip()
    physical_lower = physical.lower()
    base = physical_lower.split("(")[0].strip()
    opts = prop.get("logicalTypeOptions") or {}
    col_name = prop.get("name", "")
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
# Claim card infrastructure — improvement #5: left-border stripe + single badge
# ---------------------------------------------------------------------------

_SOURCE_META: dict[str, tuple[str, str, str]] = {
    # key: (display label, card background, left-border color)
    "ddl":        ("DDL",        "#f3f0fa", "#7c4dff"),
    "profiling":  ("Profiling",  "#e8f4fd", "#1976d2"),
    "governance": ("Governance", "#fffde7", "#ffa000"),
    "test":       ("Test",       "#f1f8e9", "#388e3c"),
    "monitor":    ("Monitor",    "#e8f5e9", "#00695c"),
}

_VERIF_META: dict[str, tuple[str, str, str]] = {
    # key: (icon, display label, badge color)
    "db_enforced": ("🏛️", "DB Enforced", "#283593"),
    "tested":      ("⚡", "Tested",       "#1b5e20"),
    "monitor":     ("📡", "Monitor",      "#00695c"),
    "monitored":   ("📡", "Monitored",    "#00695c"),
    "observed":    ("📸", "Observed",     "#546e7a"),
    "declared":    ("🏷️", "Declared",     "#795548"),
}


def _claim(name: str, value: object, source: str, verif: str, **meta: object) -> dict:
    return {"name": name, "value": str(value), "source": source, "verif": verif, **meta}


def _claim_card_html(claim: dict) -> str:
    """Static claim rendered as HTML card: left-border stripe encodes source, single verification badge."""
    src_key = claim["source"]
    verif_key = claim["verif"]
    src_label, src_bg, border_color = _SOURCE_META.get(src_key, ("?", "#f5f5f5", "#999"))
    verif_icon, verif_label, badge_color = _VERIF_META.get(verif_key, ("", verif_key, "#666"))
    name_esc = html.escape(claim["name"], quote=True)
    val_esc = html.escape(claim["value"], quote=True)
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
# Coverage helper — single definition used by health stats and per-column props
# ---------------------------------------------------------------------------

def _is_covered(prop: dict, col_rules: list[dict]) -> bool:
    """A column is 'covered' when it has at least one non-schema claim:
    a classification, CDE flag, description, format pattern, or an active test rule."""
    return bool(
        prop.get("classification")
        or prop.get("criticalDataElement")
        or prop.get("description")
        or (prop.get("logicalTypeOptions") or {}).get("format")
        or col_rules
    )


# ---------------------------------------------------------------------------
# Shared lookup builder
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
# Improvement #1 — Health dashboard
# ---------------------------------------------------------------------------

def _render_health_dashboard(
    doc: dict,
    anomalies: list[dict],
    table_group_id: str,
    is_latest: bool = True,
) -> None:
    schema = doc.get("schema") or []
    quality = doc.get("quality") or []

    all_props = [(t.get("name", ""), p) for t in schema for p in (t.get("properties") or [])]
    n_cols = len(all_props)

    rules_by_element: dict[str, list[dict]] = {}
    for rule in quality:
        rules_by_element.setdefault(rule.get("element", ""), []).append(rule)

    covered = sum(
        1 for tbl, prop in all_props
        if (
            prop.get("classification")
            or prop.get("criticalDataElement")
            or prop.get("description")
            or (prop.get("logicalTypeOptions") or {}).get("format")
            or rules_by_element.get(f"{tbl}.{prop.get('name', '')}")
            or rules_by_element.get(prop.get("name", ""))
        )
    )
    coverage_pct = int(100 * covered / n_cols) if n_cols else 0

    counts = _quality_counts(quality)
    n_tests = len(quality)
    passing = counts.get("passing", 0)
    warning_ct = counts.get("warning", 0)
    failing = counts.get("failing", 0) + counts.get("error", 0)
    not_run = counts.get("not run", 0)

    definite = sum(1 for a in anomalies if a.get("issue_likelihood") == "Definite")
    likely = sum(1 for a in anomalies if a.get("issue_likelihood") == "Likely")
    possible = sum(1 for a in anomalies if a.get("issue_likelihood") == "Possible")

    filter_key = f"dc_filter:{table_group_id}"
    active = st.session_state.get(filter_key)

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)

        with c1:
            bar_fill = int(coverage_pct / 10)
            bar = "█" * bar_fill + "░" * (10 - bar_fill)
            color = "green" if coverage_pct >= 80 else "orange" if coverage_pct >= 50 else "red"
            st.markdown(f"**Coverage** &nbsp; :{color}[{bar}] {coverage_pct}%")
            st.caption(f"{covered} of {n_cols} columns have ≥1 non-schema claim")
            uncovered = n_cols - covered
            if uncovered > 0:
                label = "✕ Clear filter" if active == "uncovered" else f"View {uncovered} uncovered →"
                if st.button(label, key=f"dc_filter_uncov:{table_group_id}", type="tertiary"):
                    st.session_state[filter_key] = None if active == "uncovered" else "uncovered"
                    safe_rerun()

        with c2:
            if n_tests == 0:
                st.markdown("**Test Health** &nbsp; ⏳ no tests defined")
                st.caption("Add quality tests to enforce claims")
            else:
                parts = []
                if passing:
                    parts.append(f"✅ {passing}")
                if warning_ct:
                    parts.append(f"⚠️ {warning_ct}")
                if failing:
                    parts.append(f"❌ {failing}")
                if not_run:
                    parts.append(f"⏳ {not_run}")
                st.markdown(f"**Test Health** &nbsp; {'  '.join(parts)}")
                st.caption(f"{n_tests} tests total")
                if failing > 0:
                    label = "✕ Clear filter" if active == "failing" else f"View {failing} failure(s) →"
                    if st.button(label, key=f"dc_filter_fail:{table_group_id}", type="tertiary"):
                        st.session_state[filter_key] = None if active == "failing" else "failing"
                        safe_rerun()

        with c3:
            if not anomalies:
                st.markdown("**Hygiene** &nbsp; ✅ clean")
                st.caption("No anomalies from latest profiling run")
            else:
                parts = []
                if definite:
                    parts.append(f"❌ {definite}")
                if likely:
                    parts.append(f"⚠️ {likely}")
                if possible:
                    parts.append(f"🔵 {possible}")
                st.markdown(f"**Hygiene** &nbsp; {'  '.join(parts)}")
                st.caption(f"{len(anomalies)} findings from latest profile run")
                label = "✕ Clear filter" if active == "anomalies" else f"View {len(anomalies)} anomalies →"
                if st.button(label, key=f"dc_filter_anom:{table_group_id}", type="tertiary"):
                    st.session_state[filter_key] = None if active == "anomalies" else "anomalies"
                    safe_rerun()
            if not is_latest:
                st.caption("⚠ Anomalies are always current — not from this snapshot.")

    if active:
        st.info(
            f"Filter active: **{active}** — showing only matching columns. "
            "Click the button above to clear.",
            icon=":material/filter_alt:",
        )


# ---------------------------------------------------------------------------
# Static vs live split  +  border-stripe cards
# ---------------------------------------------------------------------------

def _format_pii_flag(pii_flag: str) -> str:  # noqa: ARG001
    """Any non-empty pii_flag value means the column is PII."""
    return "Yes"


def _extract_column_claims(
    prop: dict,
    col_rules: list[dict],
    col_anomalies: list[dict],
    col_refs: list[dict],
    gov: dict | None = None,
) -> list[dict]:
    """Build claims for a single column.

    gov — live governance dict from data_column_chars (keyed by db column name).
    When provided it replaces the YAML-derived governance fields (classification,
    criticalDataElement, description).  Each populated governance field becomes
    one independent claim.
    """
    claims: list[dict] = []
    opts = prop.get("logicalTypeOptions") or {}
    physical = (prop.get("physicalType") or "").strip()
    physical_lower = physical.lower()
    base = physical_lower.split("(")[0].strip()

    # --- Schema claims (DDL) ---
    if physical:
        db_enforced = bool(
            _CHAR_CONSTRAINED_RE.match(physical_lower)
            or _NUMERIC_PREC_RE.match(physical_lower)
            or base in _INTEGER_TYPES
            or base in _DB_TYPED
        )
        claims.append(_claim("Data Type", physical, "ddl",
                             "db_enforced" if db_enforced else "observed", kind="static"))

    if prop.get("required") or prop.get("nullable") is False:
        claims.append(_claim("Not Null", "Required", "ddl", "db_enforced", kind="static"))

    if opts.get("primaryKey"):
        claims.append(_claim("Primary Key", "Yes", "ddl", "db_enforced", kind="static"))

    for ref in col_refs:
        claims.append(_claim("Foreign Key", f"→ {ref.get('to', '')}", "ddl", "db_enforced", kind="static"))

    # --- Governance claims (live from data_column_chars) ---
    if gov:
        if gov.get("critical_data_element"):
            claims.append(_claim("Critical Data Element", "Yes", "governance", "declared", kind="static"))
        if gov.get("excluded_data_element"):
            claims.append(_claim("Excluded Data Element", "Yes", "governance", "declared", kind="static"))
        pii = gov.get("pii_flag")
        if pii:
            claims.append(_claim("PII", _format_pii_flag(pii), "governance", "declared", kind="static"))
        desc = gov.get("description") or ""
        if desc:
            short = desc if len(desc) <= 45 else desc[:42] + "…"
            claims.append(_claim("Description", short, "governance", "declared", kind="static", full_value=desc))
        for label, col_key in _GOV_FIELDS:
            if col_key in ("critical_data_element", "excluded_data_element", "pii_flag", "description"):
                continue  # handled above
            val = gov.get(col_key) or ""
            if val:
                claims.append(_claim(label, val, "governance", "declared", kind="static"))
    else:
        # Fallback: use YAML-derived governance fields (legacy path)
        if prop.get("criticalDataElement"):
            claims.append(_claim("Critical Data Element", "Yes", "governance", "declared", kind="static"))
        if prop.get("description"):
            full_desc = str(prop["description"])
            desc_short = full_desc if len(full_desc) <= 45 else full_desc[:42] + "…"
            claims.append(_claim("Description", desc_short, "governance", "declared", kind="static",
                                 full_value=full_desc))

    # --- Profiling observations ---
    if opts.get("minimum") is not None:
        claims.append(_claim("Min Value", opts["minimum"], "profiling", "observed", kind="static"))
    if opts.get("maximum") is not None:
        claims.append(_claim("Max Value", opts["maximum"], "profiling", "observed", kind="static"))
    if opts.get("minLength") is not None:
        claims.append(_claim("Min Length", opts["minLength"], "profiling", "observed", kind="static"))
    if opts.get("maxLength") is not None:
        claims.append(_claim("Max Length", opts["maxLength"], "profiling", "observed", kind="static"))
    if opts.get("format"):
        claims.append(_claim("Format", opts["format"], "profiling", "observed", kind="static"))
    if prop.get("logicalType"):
        claims.append(_claim("Logical Type", prop["logicalType"], "profiling", "observed", kind="static"))

    # --- Live claims (tests + monitors) ---
    for rule in col_rules:
        test_name = rule.get("name") or rule.get("type") or rule.get("testType") or "Test"
        test_type = rule.get("testType", "")
        is_monitor_rule = test_type in _MONITOR_TEST_TYPES
        last = rule.get("lastResult") or {}
        status = last.get("status") or "not run"
        status_icon = _STATUS_ICON.get(status, "⏳")
        if is_monitor_rule:
            claims.append(_claim(
                "Monitor", f"{status_icon} {test_name}",
                "monitor", "monitored",
                kind="live", rule=rule, status=status,
            ))
        else:
            claims.append(_claim(
                "Test", f"{status_icon} {test_name}",
                "test", "tested",
                kind="live", rule=rule, status=status,
            ))

    for anomaly in col_anomalies:
        likelihood = anomaly.get("issue_likelihood", "")
        aname = anomaly.get("anomaly_name", "")
        likelihood_icon = {"Definite": "❌", "Likely": "⚠️", "Possible": "🔵"}.get(likelihood, "⚠️")
        claims.append(_claim(
            "Hygiene", f"{likelihood_icon} {aname}",
            "profiling", "observed",
            kind="live", anomaly=anomaly,
        ))

    return claims


def _render_live_claims_row(
    col_key: str,
    live_claims: list[dict],
    table_group_id: str,
    yaml_key: str,
) -> None:
    """Render live (test + anomaly) claims as Streamlit bordered containers with optional edit."""
    if not live_claims:
        return

    n = len(live_claims)
    cols = st.columns(min(n, 4))
    for i, claim in enumerate(live_claims):
        with cols[i % 4]:
            claim_name = claim.get("name", "Test")
            is_test = claim_name == "Test"
            is_monitor = claim_name == "Monitor"
            status = claim.get("status", "not run")
            if claim_name == "Hygiene":
                border_color = "#f9a825"
            elif is_monitor:
                border_color = (
                    "#c62828" if status in ("failing", "error") else
                    "#f9a825" if status == "warning" else
                    "#00695c" if status == "passing" else
                    "#90a4ae"
                )
            else:
                border_color = (
                    "#c62828" if status in ("failing", "error") else
                    "#f9a825" if status == "warning" else
                    "#2e7d32" if status == "passing" else
                    "#90a4ae"
                )
            label_text = "Monitor 📡" if is_monitor else ("Test" if is_test else "Hygiene")
            st.markdown(
                f'<div style="border:1px solid #e0e0e0;border-left:4px solid {border_color};'
                f'border-radius:0 6px 6px 0;padding:7px 10px;background:#fafafa;">'
                f'<div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:0.5px;">'
                f'{label_text}</div>'
                f'<div style="font-size:12px;font-weight:600;color:#1a1a1a;word-break:break-word;'
                f'margin:2px 0 0 0;">{claim["value"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if (is_test or is_monitor) and claim.get("rule"):
                rule = claim["rule"]
                rule_id = str(rule.get("id", ""))
                if rule_id:
                    btn_key = f"edit_{col_key}_{rule_id[:8]}_{i}"
                    btn_label = "📡 Detail" if is_monitor else "✏️ Edit"
                    if st.button(btn_label, key=btn_key, type="tertiary", use_container_width=True):
                        if is_monitor:
                            _monitor_claim_dialog(rule, claim_name)
                        else:
                            _edit_rule_dialog(rule, table_group_id, yaml_key)



# ---------------------------------------------------------------------------
# Improvement #6 — Inline editing dialog
# ---------------------------------------------------------------------------

_SRC_LABEL = {"ddl": "DDL", "profiling": "Profiling", "governance": "Governance", "test": "Test"}
_VERIF_LABEL = {
    "db_enforced": "🏛️ DB Enforced",
    "tested":      "⚡ Tested",
    "monitored":   "📡 Monitored",
    "observed":    "📸 Observed",
    "declared":    "🏷️ Declared",
}
_SRC_NOTE = {
    "ddl":       "Column type, constraints, and keys come from the physical database schema. "
                 "These values are enforced by the database and cannot be changed here.",
    "profiling": "This value was measured from actual data during a profiling run. "
                 "It is a snapshot of what TestGen observed, not an active constraint.",
}

# Claims that can be removed from the YAML for each source type.
# DDL claims re-appear after a contract refresh since they derive from the live schema.
_DELETABLE_CLAIMS: dict[str, set[str]] = {
    "governance": {"Classification", "CDE", "Description"},
    "profiling":  {"Min Value", "Max Value", "Min Length", "Max Length", "Format", "Logical Type"},
    "ddl":        {"Not Null", "Primary Key", "Foreign Key", "Data Type"},
}


def _delete_claim_yaml_patch(
    claim_name: str,
    source: str,
    table_name: str,
    col_name: str,
    claim_value: str,
    doc: dict,
) -> tuple[bool, str]:
    """Remove a claim from the in-memory contract YAML doc.
    Returns (patched: bool, error_msg: str).
    """
    col_key = f"{table_name}.{col_name}"

    # Foreign key lives in the top-level references list, not in schema properties.
    if source == "ddl" and claim_name == "Foreign Key":
        refs = doc.get("references") or []
        before = len(refs)
        def _ref_matches(r: dict) -> bool:
            from_val = r.get("from")
            if isinstance(from_val, list):
                return col_key in from_val or col_name in from_val
            return from_val in (col_key, col_name)

        doc["references"] = [r for r in refs if not _ref_matches(r)]
        return len(doc["references"]) < before, "Foreign key reference not found."

    for tbl in (doc.get("schema") or []):
        if tbl.get("name") != table_name:
            continue
        for prop in (tbl.get("properties") or []):
            if prop.get("name") != col_name:
                continue

            opts: dict = prop.setdefault("logicalTypeOptions", {})

            if source == "governance":
                if claim_name == "Classification":
                    prop.pop("classification", None)
                elif claim_name == "CDE":
                    prop.pop("criticalDataElement", None)
                elif claim_name == "Description":
                    prop.pop("description", None)

            elif source == "profiling":
                if claim_name == "Min Value":
                    opts.pop("minimum", None)
                elif claim_name == "Max Value":
                    opts.pop("maximum", None)
                elif claim_name == "Min Length":
                    opts.pop("minLength", None)
                elif claim_name == "Max Length":
                    opts.pop("maxLength", None)
                elif claim_name == "Format":
                    opts.pop("format", None)
                elif claim_name == "Logical Type":
                    prop.pop("logicalType", None)

            elif source == "ddl":
                if claim_name == "Data Type":
                    prop.pop("physicalType", None)
                elif claim_name == "Not Null":
                    prop.pop("required", None)
                    prop.pop("nullable", None)
                elif claim_name == "Primary Key":
                    opts.pop("primaryKey", None)

            # Remove empty opts dict to keep YAML tidy
            if not opts:
                prop.pop("logicalTypeOptions", None)

            return True, ""

    return False, f"Could not locate `{table_name}.{col_name}` in the contract."


@with_database_session
def _persist_governance_deletion(
    claim_name: str,
    table_group_id: str,
    table_name: str,
    col_name: str,
) -> None:
    """Write a governance claim deletion directly to data_column_chars so it survives the next export."""
    schema = get_tg_schema()
    field_map: dict[str, tuple[str, object]] = {
        "Description":    ("description",          None),
        "CDE":            ("critical_data_element", False),
        "Classification": ("pii_flag",              None),
    }
    entry = field_map.get(claim_name)
    if not entry:
        return
    db_col, db_val = entry
    execute_db_queries([(
        f"UPDATE {schema}.data_column_chars SET {db_col} = :val "
        "WHERE table_groups_id = :tg_id AND table_name = :tbl AND column_name = :col",
        {"val": db_val, "tg_id": table_group_id, "tbl": table_name, "col": col_name},
    )])


def _modal_header(verif: str, name: str, table_name: str, col_name: str, subtitle: str = "") -> None:
    """Render a consistent modal header.

    Line 1 (bold): {icon} {verif_label} — {name}
    Line 2 (caption): table_name
    Line 3 (caption mono): col_name
    Optional subtitle below.
    """
    icon, label, _ = _VERIF_META.get(verif, ("", verif.replace("_", " ").title(), ""))
    header_line = f"{icon} {label} \u2014 {html.escape(name)}" if label else html.escape(name)
    if table_name and col_name:
        location = f"{html.escape(table_name)} · {html.escape(col_name)}"
    elif table_name:
        location = html.escape(table_name)
    else:
        location = html.escape(col_name) if col_name else ""
    location_html = (
        f'<div style="font-size:12px;color:var(--caption-text-color);margin-top:3px;font-family:monospace;">{location}</div>'
        if location else ""
    )
    subtitle_html = (
        f'<p style="margin:8px 0 0 0;font-size:13px;color:var(--secondary-text-color);line-height:1.5;">'
        f'{html.escape(subtitle)}</p>'
        if subtitle else ""
    )
    st.markdown(
        f"""
        <div style="padding:4px 0 12px 0;border-bottom:1px solid var(--border-color);margin-bottom:14px;">
          <div style="font-size:17px;font-weight:700;color:var(--primary-text-color);line-height:1.3;">
            {header_line}
          </div>
          {location_html}
          {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("Governance Metadata", width="large")
def _governance_edit_dialog(
    column_id: str,
    table_name: str,
    col_name: str,
    table_group_id: str,
    yaml_key: str,
) -> None:
    """Edit all governance metadata for a column, writing directly to data_column_chars."""
    # Re-fetch current values so the dialog is always fresh
    gov_map = _fetch_governance_data(table_group_id)
    gov = gov_map.get((table_name, col_name)) or {}

    # If still no column_id, try looking it up from gov_map or the passed-in id
    effective_column_id = column_id or gov.get("column_id", "")

    if not effective_column_id:
        st.warning(
            f"Column `{col_name}` in `{table_name}` has no governance record yet. "
            "Run profiling first to create the column record, then you can set metadata here."
        )
        if st.button("Close"):
            safe_rerun()
        return

    can_edit_pii = session.auth.user_has_permission("view_pii")

    _modal_header("declared", "Governance Metadata", table_name, col_name)

    updates: dict = {}

    # ── Boolean flags ──────────────────────────────────────────────────────────
    f1, f2 = st.columns(2)
    updates["critical_data_element"] = f1.toggle(
        "Critical Data Element",
        value=bool(gov.get("critical_data_element")),
        help="Mark this column as a Critical Data Element (CDE).",
    )
    updates["excluded_data_element"] = f2.toggle(
        "Excluded Data Element",
        value=bool(gov.get("excluded_data_element")),
        help="Exclude this column from quality test generation.",
    )

    # ── PII ────────────────────────────────────────────────────────────────────
    if can_edit_pii:
        current_pii = gov.get("pii_flag")
        is_pii = st.checkbox("Contains PII", value=bool(current_pii))
        updates["pii_flag"] = "MANUAL" if is_pii else None
    else:
        st.caption("🔒 PII classification: requires view_pii permission to edit.")

    st.divider()

    # ── Description ────────────────────────────────────────────────────────────
    updates["description"] = st.text_area(
        "Description",
        value=gov.get("description") or "",
        height=80,
        placeholder="Describe what this column contains…",
    )

    st.divider()

    # ── Tag fields ─────────────────────────────────────────────────────────────
    tag_labels = {
        "data_source":      "Data Source",
        "source_system":    "Source System",
        "source_process":   "Source Process",
        "business_domain":  "Business Domain",
        "stakeholder_group": "Stakeholder Group",
        "transform_level":  "Transform Level",
        "aggregation_level": "Aggregation Level",
        "data_product":     "Data Product",
    }
    c1, c2 = st.columns(2)
    for i, (db_col, label) in enumerate(tag_labels.items()):
        col_widget = c1 if i % 2 == 0 else c2
        updates[db_col] = col_widget.text_input(
            label,
            value=gov.get(db_col) or "",
            max_chars=40,
        )

    st.divider()
    save_col, cancel_col = st.columns(2)
    if save_col.button("Save", type="primary", use_container_width=True):
        _save_governance_data(effective_column_id, updates)
        # Clear cached contract so claims refresh on next render
        st.session_state.pop(yaml_key, None)
        safe_rerun()
    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


@st.dialog("Select Test Suite", width="small")
def _suite_picker_dialog(suite_runs: list[dict]) -> None:
    """Let the user choose which suite's results to drill into."""
    st.caption("This contract covers multiple test suites. Choose one to view its results.")
    for sr in suite_runs:
        total  = sr.get("test_ct", 0)
        passed = sr.get("passed_ct", 0)
        failed = sr.get("failed_ct", 0) + sr.get("error_ct", 0)
        warn   = sr.get("warning_ct", 0)
        date   = sr.get("run_start", "")
        name   = sr.get("suite_name", "")

        border_color = "#c62828" if failed else "#f9a825" if warn else "#2e7d32"
        status_parts: list[str] = []
        if passed: status_parts.append(f"✅ {passed} passed")
        if warn:   status_parts.append(f"⚠️ {warn} warnings")
        if failed: status_parts.append(f"❌ {failed} failed")
        sub = "  ·  ".join(status_parts) if status_parts else f"{total} tests"
        if date:
            sub += f"  ·  {date}"

        c_info, c_btn = st.columns([3, 1])
        with c_info:
            st.markdown(
                f'<div style="border-left:3px solid {border_color};padding:5px 10px;margin:4px 0;">'
                f'<div style="font-size:13px;font-weight:600;">{name}</div>'
                f'<div style="font-size:11px;color:#888;">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        if c_btn.button("Open →", key=f"suite_pick_{sr['run_id']}"):
            Router().queue_navigation(to="test-runs:results", with_args={"run_id": sr["run_id"]})
            safe_rerun()

    st.divider()
    if st.button("Cancel", key="suite_pick_cancel", use_container_width=True):
        safe_rerun()


_MONITOR_ICON: dict[str, str] = {
    "Freshness_Trend": "🕐",
    "Volume_Trend":    "📊",
    "Schema_Drift":    "🗂️",
    "Metric_Trend":    "📈",
}

_MONITOR_DESCRIPTION: dict[str, str] = {
    "Freshness_Trend": "Detects stale data — alerts when a table stops updating on its expected schedule.",
    "Volume_Trend":    "Detects unusual row count changes — alerts when volume spikes or drops outside the expected range.",
    "Schema_Drift":    "Detects schema changes — alerts when columns are added, dropped, or modified.",
    "Metric_Trend":    "Detects anomalies in a numeric metric — alerts when the value drifts outside historical norms.",
}


@st.dialog("Monitor Claim Detail", width="small")
def _monitor_claim_dialog(rule: dict, claim_name: str, table_name: str = "", col_name: str = "") -> None:  # noqa: ARG001
    test_type = rule.get("testType", "")
    icon = _MONITOR_ICON.get(test_type, "📡")
    description = _MONITOR_DESCRIPTION.get(test_type, "A continuous monitor watches this element for anomalies over time.")
    monitor_name = rule.get("name") or test_type or "Monitor"
    last = rule.get("lastResult") or {}
    status = last.get("status") or "not run"
    status_icon = _STATUS_ICON.get(status, "⏳")

    _modal_header("monitored", monitor_name, table_name, col_name, subtitle=description)
    st.divider()
    st.markdown(f"**Status** &nbsp; {status_icon} {status.title() if status else 'Not Run'}")
    if last.get("measuredValue") is not None:
        st.markdown(f"**Last Measured** &nbsp; `{last['measuredValue']}`")
    if last.get("executedAt"):
        st.markdown(f"**Last Run** &nbsp; {last['executedAt']}")
    st.divider()
    st.caption("📡 Managed in TestGen Monitors. To configure or run it, go to Monitors.")
    if st.button("Close", key="monitor_claim_close", use_container_width=True):
        safe_rerun()


@st.dialog("Test Claim Detail", width="small")
def _test_claim_dialog(claim: dict, table_name: str, col_name: str, project_code: str) -> None:
    status = claim.get("status", "")
    status_icon = _STATUS_ICON.get(status, "⏳")
    test_name = claim.get("test_name") or "Test"
    element = claim.get("element") or f"{table_name}.{col_name}"
    dimension = claim.get("dimension", "")
    severity = claim.get("severity", "")
    rule_id = claim.get("rule_id", "")

    # Fetch live status + timestamp + suite_id from the DB
    live_info = _fetch_test_live_info(rule_id) if rule_id else {}
    suite_id  = live_info.get("suite_id", "")
    live_status = live_info.get("status", "") or status  # fall back to claim status
    live_status_icon = _STATUS_ICON.get(live_status, "⏳")
    test_time = live_info.get("test_time")

    # Format the last-run timestamp for display
    if test_time:
        try:
            from datetime import timezone as _tz
            dt = test_time if hasattr(test_time, "strftime") else None
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=_tz.utc)
                last_run_display = dt.astimezone().strftime("%b %d, %Y %H:%M")
            else:
                last_run_display = str(test_time)
        except Exception:
            last_run_display = str(test_time)
    else:
        last_run_display = None

    test_name_short  = live_info.get("test_name_short") or test_name
    type_description = live_info.get("type_description") or ""
    user_description = live_info.get("user_description") or ""
    status_label = live_status.title() if live_status else "Not Run"

    subtitle = type_description
    if user_description:
        subtitle = f"{subtitle}\n**Notes:** {user_description}" if subtitle else f"**Notes:** {user_description}"

    _modal_header("tested", test_name_short, table_name, col_name, subtitle=type_description)
    if user_description:
        st.caption(f"Notes: {user_description}")

    meta: list[tuple[str, str]] = [
        ("Status", f"{live_status_icon} {status_label}"),
        ("Last Run", last_run_display or "Not run"),
    ]
    if dimension:
        meta.append(("Dimension", dimension.title()))
    if severity:
        meta.append(("Severity", severity.title()))

    cols = st.columns(len(meta))
    for col_st, (label, value) in zip(cols, meta):
        col_st.markdown(
            f'<div style="font-size:11px;color:var(--caption-text-color);font-weight:600;'
            f'text-transform:uppercase;letter-spacing:0.4px;margin-bottom:2px;">{label}</div>'
            f'<div style="font-size:13px;color:var(--primary-text-color);">{value}</div>',
            unsafe_allow_html=True,
        )

    st.divider()
    btn_col, close_col = st.columns(2)
    if suite_id and project_code:
        if btn_col.button("Edit test", key="test_claim_goto", use_container_width=True):
            Router().queue_navigation(
                to="test-suites:definitions",
                with_args={"test_suite_id": suite_id, "project_code": project_code},
            )
            safe_rerun()
    if close_col.button("Close", key="test_claim_close", use_container_width=True):
        safe_rerun()


@st.dialog("Claim Detail", width="small")
def _claim_read_dialog(
    claim: dict,
    table_name: str,
    col_name: str,
    table_group_id: str,
    yaml_key: str,
) -> None:
    src        = claim.get("source", "")
    verif      = claim.get("verif", "")
    claim_name = claim.get("name", "")
    can_delete = claim_name in _DELETABLE_CLAIMS.get(src, set())

    _modal_header(verif, claim_name, table_name, col_name)
    st.divider()
    st.write(claim.get("full_value") or claim.get("value", ""))
    note = _SRC_NOTE.get(src, "")
    if note:
        st.caption(f"ℹ️ {note}")
    if src == "ddl" and can_delete:
        st.caption("⚠️ Schema-derived claims will reappear after the next contract refresh.")

    if src in ("profiling", "ddl") and can_delete:
        st.caption("⚠️ This change is temporary and will reset on the next contract refresh.")

    st.divider()
    if can_delete:
        del_col, close_col = st.columns(2)
        if del_col.button("Delete Claim", key="claim_read_delete", use_container_width=True):
            current_yaml = st.session_state.get(yaml_key, "")
            try:
                _parsed = yaml.safe_load(current_yaml)
                doc = _parsed if isinstance(_parsed, dict) else {}
            except yaml.YAMLError:
                st.error("Could not parse the contract YAML.")
                return
            patched, err = _delete_claim_yaml_patch(
                claim_name, src, table_name, col_name, claim.get("value", ""), doc
            )
            if not patched:
                st.error(err or "Could not remove this claim.")
                return
            patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
            # Governance: persist to DB so the deletion survives contract refresh
            if src == "governance":
                _persist_governance_deletion(claim_name, table_group_id, table_name, col_name)
            # Store the patched YAML in session — do NOT pop and re-export, which would restore the claim
            st.session_state[yaml_key] = patched_yaml
            safe_rerun()
        if close_col.button("Close", key="claim_read_close", use_container_width=True):
            safe_rerun()
    else:
        if st.button("Close", key="claim_read_close", use_container_width=True):
            safe_rerun()


@st.dialog("Edit Governance Claim", width="small")
def _claim_edit_dialog(
    claim: dict,
    table_name: str,
    col_name: str,
    table_group_id: str,
    yaml_key: str,
) -> None:
    claim_name = claim.get("name", "")
    current_value = claim.get("full_value") or claim.get("value", "")

    _modal_header("declared", claim_name, table_name, col_name)

    if claim_name == "CDE":
        new_cde: bool = st.checkbox("Mark as Critical Data Element", value=True)
        new_value: str = "true" if new_cde else ""
    elif claim_name == "Description":
        new_value = st.text_area("Description", value=current_value, height=120)
    else:
        new_value = st.text_input(claim_name, value=current_value)

    st.divider()
    save_col, cancel_col = st.columns(2)

    st.caption("ℹ Changes are held until you save a new contract version.")

    if save_col.button("Save", type="primary", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            _parsed = yaml.safe_load(current_yaml)
            doc = _parsed if isinstance(_parsed, dict) else {}
        except yaml.YAMLError:
            st.error("Could not parse the contract YAML.")
            return

        edit_value: object = new_value
        if claim_name == "CDE":
            edit_value = new_cde

        patched = _patch_yaml_governance(doc, table_name, col_name, claim_name, edit_value)

        if not patched:
            st.warning(f"Could not locate `{table_name}.{col_name}` in the contract — no changes made.")
            return

        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        st.session_state[yaml_key] = patched_yaml
        pending_key = f"dc_pending:{table_group_id}"
        LOG.debug("Pending governance edit: %s.%s %s = %r", table_name, col_name, claim_name, edit_value)
        st.session_state[pending_key] = _apply_pending_governance_edit(
            st.session_state.get(pending_key, {}),
            table_name, col_name, claim_name, edit_value,
        )
        safe_rerun()

    if cancel_col.button("Close", use_container_width=True):
        safe_rerun()

    st.divider()
    if st.button("Delete Claim", key="claim_edit_delete", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            _parsed = yaml.safe_load(current_yaml)
            doc = _parsed if isinstance(_parsed, dict) else {}
        except yaml.YAMLError:
            st.error("Could not parse the contract YAML.")
            return
        patched, err = _delete_claim_yaml_patch(
            claim_name, "governance", table_name, col_name, current_value, doc
        )
        if not patched:
            st.error(err or "Could not remove this claim.")
            return
        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        st.session_state[yaml_key] = patched_yaml
        pending_key = f"dc_pending:{table_group_id}"
        st.session_state[pending_key] = _apply_pending_governance_edit(
            st.session_state.get(pending_key, {}),
            table_name, col_name, claim_name, None,
        )
        safe_rerun()


@st.dialog("Edit Quality Rule", width="small")
def _edit_rule_dialog(rule: dict, table_group_id: str, yaml_key: str) -> None:
    rule_id = str(rule.get("id", ""))
    test_name = rule.get("name") or rule.get("type") or "Test"
    last = rule.get("lastResult") or {}

    st.markdown(f"**{test_name}**")
    if rule.get("element"):
        st.caption(f"Element: `{rule['element']}`")
    if last.get("status"):
        icon = _STATUS_ICON.get(last["status"], "")
        st.caption(f"Last result: {icon} {last['status']}")

    op_key = next(
        (k for k in ("mustBe", "mustBeGreaterThan", "mustBeGreaterOrEqualTo",
                     "mustBeLessThan", "mustBeLessOrEqualTo")
         if k in rule),
        None,
    )
    has_between = "mustBeBetween" in rule and isinstance(rule["mustBeBetween"], list)

    new_threshold = ""
    new_lo: str | None = None
    new_hi: str | None = None

    if op_key:
        new_threshold = st.text_input(
            f"Threshold ({op_key})",
            value=str(rule[op_key]),
            help="The numeric value this test must satisfy.",
        )
    elif has_between:
        lo, hi = rule["mustBeBetween"][0], rule["mustBeBetween"][1]
        col_lo, col_hi = st.columns(2)
        new_lo = col_lo.text_input("Lower bound", value=str(lo))
        new_hi = col_hi.text_input("Upper bound", value=str(hi))

    new_desc = st.text_input(
        "Description",
        value=rule.get("name") or "",
        help="Human-readable name shown in contract and test results.",
    )

    severity_options = [None, "Log", "Warning", "Failed"]
    current_sev = rule.get("severity")
    try:
        sev_index = severity_options.index(current_sev)
    except ValueError:
        sev_index = 0
    new_severity = st.radio(
        "Severity",
        options=severity_options,
        index=sev_index,
        format_func=lambda v: "Inherit" if v is None else v,
        horizontal=True,
    )

    st.caption("ℹ Changes are held until you save a new contract version.")
    st.divider()
    save_col, cancel_col = st.columns(2)

    if save_col.button("Save", type="primary", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            _parsed = yaml.safe_load(current_yaml)
            doc = _parsed if isinstance(_parsed, dict) else {}
        except yaml.YAMLError:
            st.error("Could not parse current contract YAML.")
            return

        quality = doc.get("quality") or []
        patched = False
        test_updates: dict = {}
        for q in quality:
            if str(q.get("id", "")) == rule_id:
                if op_key and new_threshold:
                    try:
                        q[op_key] = float(new_threshold) if "." in str(new_threshold) else int(new_threshold)
                        test_updates[op_key] = q[op_key]
                    except ValueError:
                        q[op_key] = new_threshold
                        test_updates[op_key] = new_threshold
                if has_between and new_lo is not None and new_hi is not None:
                    try:
                        q["mustBeBetween"] = [
                            float(new_lo) if "." in new_lo else int(new_lo),
                            float(new_hi) if "." in new_hi else int(new_hi),
                        ]
                        test_updates["mustBeBetween"] = q["mustBeBetween"]
                    except ValueError:
                        pass
                if new_desc and new_desc != (rule.get("name") or ""):
                    q["name"] = new_desc
                    test_updates["name"] = new_desc
                if new_severity != current_sev:
                    if new_severity is None:
                        q.pop("severity", None)
                        test_updates["severity"] = None
                    else:
                        q["severity"] = new_severity
                        test_updates["severity"] = new_severity
                patched = True
                break

        if not patched:
            st.warning(f"Rule `{rule_id[:8]}…` not found in contract YAML — no changes made.")
            return

        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        st.session_state[yaml_key] = patched_yaml
        pending_key = f"dc_pending:{table_group_id}"
        LOG.debug("Pending test edit: rule %s updates %r", rule_id, test_updates)
        st.session_state[pending_key] = _apply_pending_test_edit(
            st.session_state.get(pending_key, {}),
            rule_id,
            test_updates,
        )
        safe_rerun()

    if cancel_col.button("Close", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Props builder — pre-computes all display data for VanJS
# ---------------------------------------------------------------------------

def _build_contract_props(
    table_group: object,
    doc: dict,
    anomalies: list[dict],
    contract_yaml: str,
    run_dates: dict | None = None,
    suite_scope: dict | None = None,
    test_statuses: dict[str, str] | None = None,
) -> dict:
    schema: list[dict] = doc.get("schema") or []
    quality: list[dict] = doc.get("quality") or []
    references: list[dict] = doc.get("references") or []

    # Inject fresh test statuses — overrides whatever was cached in the YAML
    if test_statuses:
        for rule in quality:
            rule_id = rule.get("id", "")
            if rule_id in test_statuses:
                rule.setdefault("lastResult", {})["status"] = test_statuses[rule_id]
            elif rule_id and "lastResult" not in rule:
                pass  # no result yet — leave as absent (shows "not run")
    servers: list[dict] = doc.get("servers") or []

    # ── Meta ──────────────────────────────────────────────────────────────────
    description = doc.get("description") or {}
    description_purpose = (
        description.get("purpose") if isinstance(description, dict) else str(description)
    ) or ""

    meta = {
        "status":              doc.get("status", "draft"),
        "version":             doc.get("version") or "",
        "domain":              doc.get("domain") or "",
        "data_product":        doc.get("dataProduct") or "",
        "description_purpose": description_purpose,
        "server_type":         servers[0].get("type", "") if servers else "",
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
        "coverage_pct":       coverage_pct,
        "covered":            covered,
        "n_cols":             n_cols,
        "n_tests":            len(quality),
        "passing":            counts.get("passing", 0),
        "warning":            counts.get("warning", 0),
        "failing":            counts.get("failing", 0) + counts.get("error", 0),
        "not_run":            counts.get("not run", 0),
        "hygiene_total":      len(anomalies),
        "hygiene_definite":   sum(1 for a in anomalies if a.get("issue_likelihood") == "Definite"),
        "hygiene_likely":     sum(1 for a in anomalies if a.get("issue_likelihood") == "Likely"),
        "hygiene_possible":   sum(1 for a in anomalies if a.get("issue_likelihood") == "Possible"),
        "last_test_run":        _fmt_ts(rd.get("last_test_run")),
        "last_test_run_id":     str(rd["last_test_run_id"]) if rd.get("last_test_run_id") else None,
        "last_profiling_run":   _fmt_ts(rd.get("last_profiling_run")),
        "last_profiling_run_id": str(rd["last_profiling_run_id"]) if rd.get("last_profiling_run_id") else None,
        "suites_included":    len(_scope.get("included", [])),
        "suites_total":       _scope.get("total", 0),
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

    # ── Governance metadata (live from data_column_chars) — needed for matrix + claims ──
    table_group_id_str = str(getattr(table_group, "id", "") or "")
    gov_by_col = _fetch_governance_data(table_group_id_str)

    # ── Coverage matrix rows ──────────────────────────────────────────────────
    rules_by_element_full, anomalies_by_col, refs_by_col = _build_lookups(quality, references, anomalies)
    matrix_rows: list[dict] = []
    for table in schema:
        table_name = table.get("name", "")
        tbl_rules_mx = rules_by_element_full.get(table_name, [])
        if tbl_rules_mx:
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
            })
        for prop in (table.get("properties") or []):
            col_name = prop.get("name", "")
            col_key = f"{table_name}.{col_name}"
            opts = prop.get("logicalTypeOptions") or {}
            col_rules = rules_by_element_full.get(col_key, []) + rules_by_element_full.get(col_name, [])
            col_anomalies = anomalies_by_col.get((table_name, col_name), [])
            col_refs = refs_by_col.get(col_key, []) + refs_by_col.get(col_name, [])
            test_counts = _quality_counts(col_rules)
            worst_test = _worst_status(test_counts) if col_rules else None
            worst_anomaly: str | None = None
            for a in col_anomalies:
                lk = a.get("issue_likelihood", "")
                if lk == "Definite":
                    worst_anomaly = "Definite"
                    break
                if lk == "Likely" and worst_anomaly != "Definite":
                    worst_anomaly = "Likely"
                elif not worst_anomaly:
                    worst_anomaly = "Possible"
            physical = (prop.get("physicalType") or "").strip()
            physical_lower = physical.lower()
            base_type = physical_lower.split("(")[0].strip()
            is_db_typed = bool(physical and (
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
            mon_ct = sum(1 for r in col_rules if r.get("testType", "") in _MONITOR_TEST_TYPES)
            obs_ct = sum([
                # unconstrained physicalType (TEXT, etc.) → observed
                1 if (physical and not is_db_typed) else 0,
                # profiling observations from logicalTypeOptions
                1 if opts.get("minimum") is not None else 0,
                1 if opts.get("maximum") is not None else 0,
                1 if opts.get("minLength") is not None else 0,
                1 if opts.get("maxLength") is not None else 0,
                1 if opts.get("format") else 0,
                1 if prop.get("logicalType") else 0,
                # profiling hygiene anomalies
                len(col_anomalies),
            ])
            gov_col = gov_by_col.get((table_name, col_name)) or {}
            decl_ct = sum([
                1 if (gov_col.get("description") or prop.get("description")) else 0,
                1 if (gov_col.get("pii_flag") or prop.get("classification")) else 0,
                1 if (gov_col.get("critical_data_element") or prop.get("criticalDataElement")) else 0,
                # additional gov fields
                sum(1 for _, db_col in _GOV_FIELDS
                    if db_col not in ("description", "pii_flag", "critical_data_element",
                                      "excluded_data_element")
                    and gov_col.get(db_col)),
            ])
            matrix_rows.append({
                "table":    table_name,
                "column":   col_name,
                "db":       db_ct,
                "tested":   tested_ct,
                "mon":      mon_ct,
                "obs":      obs_ct,
                "decl":     decl_ct,
            })

    # ── Gap analysis ──────────────────────────────────────────────────────────
    gap_items: list[dict] = []  # {table, msg, severity}
    for table in schema:
        table_name = table.get("name", "")
        table_has_tests = False
        for prop in (table.get("properties") or []):
            col_name = prop.get("name", "")
            col_key = f"{table_name}.{col_name}"
            col_rules = rules_by_element_full.get(col_key, []) + rules_by_element_full.get(col_name, [])
            opts = prop.get("logicalTypeOptions") or {}
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

    # ── Per-table column claims ───────────────────────────────────────────────
    tables_data: list[dict] = []
    for table in schema:
        table_name = table.get("name", "")

        # Table-level rules: element matches the table name exactly (e.g. row count tests)
        tbl_rules = rules_by_element_full.get(table_name, [])
        table_claims: list[dict] = [
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
            col_name = prop.get("name", "")
            col_key = f"{table_name}.{col_name}"
            col_rules = rules_by_element_full.get(col_key, []) + rules_by_element_full.get(col_name, [])
            col_anomalies = anomalies_by_col.get((table_name, col_name), [])
            col_refs = refs_by_col.get(col_key, []) + refs_by_col.get(col_name, [])
            gov = gov_by_col.get((table_name, col_name))
            claims = _extract_column_claims(prop, col_rules, col_anomalies, col_refs, gov=gov)
            static_claims = [c for c in claims if c.get("kind") == "static"]
            live_claims   = [c for c in claims if c.get("kind") == "live"]
            worst_live = "clean"
            for c in live_claims:
                s = c.get("status", "")
                if s in ("failing", "error"):
                    worst_live = "failing"
                    break
                if s == "warning" and worst_live != "failing":
                    worst_live = "warning"
                if c.get("name") == "Hygiene" and worst_live == "clean":
                    worst_live = "warning"
            col_refs_full = refs_by_col.get(col_key, []) + refs_by_col.get(col_name, [])
            is_covered = _is_covered(prop, col_rules)
            column_id = (gov or {}).get("column_id", "")
            cols_data.append({
                "name":          col_name,
                "type":          prop.get("physicalType") or "",
                "is_pk":         bool((prop.get("logicalTypeOptions") or {}).get("primaryKey")),
                "is_fk":         bool(col_refs_full),
                "column_id":     column_id,
                "covered":       is_covered,
                "status":        worst_live,
                "static_claims": [
                    {"name": c["name"], "value": c["value"], "source": c["source"], "verif": c["verif"]}
                    for c in static_claims
                ],
                "live_claims": [
                    {
                        "name":        c["name"],
                        "value":       c["value"],
                        "source":      c["source"],
                        "verif":       c["verif"],
                        "status":      c.get("status") or "",
                        "rule_id":     str(c.get("rule", {}).get("id", "") or ""),
                        "suite_id":    str(c.get("rule", {}).get("suiteId", "") or ""),
                        "test_name":   (c.get("rule", {}).get("name") or c.get("rule", {}).get("testType") or ""),
                        "test_type":   (c.get("rule", {}).get("type") or c.get("rule", {}).get("testType") or ""),
                        "element":     (c.get("rule", {}).get("element") or ""),
                        "dimension":   (c.get("rule", {}).get("dimension") or ""),
                        "severity":    (c.get("rule", {}).get("severity") or ""),
                        "executed_at": ((c.get("rule", {}).get("lastResult") or {}).get("executedAt") or ""),
                    }
                    for c in live_claims
                ],
            })
        if cols_data or table_claims:
            tables_data.append({
                "name":         table_name,
                "column_count": len(cols_data),
                "table_claims": table_claims,
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


# ---------------------------------------------------------------------------
# Pure helpers for pending edits (unit-testable without Streamlit)
# ---------------------------------------------------------------------------

def _apply_pending_governance_edit(
    pending: dict,
    table_name: str,
    col_name: str,
    field: str,
    value: object,
) -> dict:
    """Add or replace a governance edit in the pending dict. Returns updated pending."""
    gov = [
        e for e in pending.get("governance", [])
        if not (e["table"] == table_name and e["col"] == col_name and e["field"] == field)
    ]
    gov.append({"table": table_name, "col": col_name, "field": field, "value": value})
    return {**pending, "governance": gov}


def _apply_pending_test_edit(
    pending: dict,
    rule_id: str,
    updates: dict,
) -> dict:
    """Add or replace a test edit in the pending dict. Returns updated pending."""
    tests = [e for e in pending.get("tests", []) if e.get("rule_id") != rule_id]
    tests.append({"rule_id": rule_id, **updates})
    return {**pending, "tests": tests}


def _pending_edit_count(pending: dict) -> int:
    """Total number of pending edits across all categories."""
    return len(pending.get("governance", [])) + len(pending.get("tests", []))


def _patch_yaml_governance(doc: dict, table_name: str, col_name: str, field: str, value: object) -> bool:
    """Patch a governance field in-place on the parsed YAML doc. Returns True if patched."""
    field_map = {"Classification": "classification", "Description": "description", "CDE": "criticalDataElement"}
    yaml_field = field_map.get(field, field)
    for tbl in (doc.get("schema") or []):
        if tbl.get("name") == table_name:
            for prop in (tbl.get("properties") or []):
                if prop.get("name") == col_name:
                    if value is None or value == "" or value is False:
                        prop.pop(yaml_field, None)
                    else:
                        prop[yaml_field] = value
                    return True
    return False


# ---------------------------------------------------------------------------
# First-time flow prerequisite check
# ---------------------------------------------------------------------------

@with_database_session
def _check_contract_prerequisites(table_group_id: str) -> dict:
    """Check whether the prerequisites for generating a first contract are met."""
    from testgen.common.credentials import get_tg_schema
    from testgen.common.database.database_service import fetch_dict_from_db
    schema = get_tg_schema()

    # Last profiling run
    profiling_rows = fetch_dict_from_db(
        f"SELECT MAX(profiling_starttime) AS last_run FROM {schema}.profiling_runs "
        f"WHERE table_groups_id = :tg_id AND status = 'Complete'",
        params={"tg_id": table_group_id},
    )
    last_profiling = dict(profiling_rows[0]).get("last_run") if profiling_rows else None

    # Non-monitor suite count with active tests
    suite_rows = fetch_dict_from_db(
        f"SELECT COUNT(*) AS ct FROM {schema}.test_suites ts "
        f"JOIN {schema}.test_definitions td ON td.test_suite_id = ts.id "
        f"WHERE ts.table_groups_id = :tg_id AND ts.is_monitor IS NOT TRUE "
        f"AND td.test_active = 'Y'",
        params={"tg_id": table_group_id},
    )
    suite_ct = int(dict(suite_rows[0]).get("ct", 0)) if suite_rows else 0

    # Column metadata coverage
    meta_rows = fetch_dict_from_db(
        f"SELECT COUNT(*) AS total, "
        f"SUM(CASE WHEN description IS NOT NULL OR pii_flag IS NOT NULL THEN 1 ELSE 0 END) AS with_meta "
        f"FROM {schema}.data_column_chars WHERE table_groups_id = :tg_id",
        params={"tg_id": table_group_id},
    )
    if meta_rows:
        mr = dict(meta_rows[0])
        total = int(mr.get("total") or 0)
        with_meta = int(mr.get("with_meta") or 0)
        meta_pct = int(100 * with_meta / total) if total else 0
    else:
        meta_pct = 0

    return {
        "has_profiling": last_profiling is not None,
        "last_profiling": last_profiling,
        "has_suites": suite_ct > 0,
        "suite_ct": suite_ct,
        "meta_pct": meta_pct,
    }


# ---------------------------------------------------------------------------
# Staleness banner
# ---------------------------------------------------------------------------

def _render_staleness_banner(
    version_record: dict,
    stale_diff: StaleDiff,
    table_group_id: str,
    dismissed_key: str,
) -> None:
    """Render the staleness warning banner. Returns silently if not stale or dismissed."""
    if st.session_state.get(dismissed_key):
        return
    parts = stale_diff.summary_parts()
    saved_at = version_record.get("saved_at")
    saved_str = saved_at.strftime("%b %d, %Y") if saved_at else "unknown date"
    version_num = version_record.get("version", "?")
    st.warning(
        f"Contract version {version_num} was saved on {saved_str}. "
        f"Since then: {', '.join(parts)}.",
        icon="⚠️",
    )
    col1, col2 = st.columns([1, 8])
    if col1.button("Review Changes", key=f"dc_review_changes:{table_group_id}"):
        st.session_state[f"dc_show_review:{table_group_id}"] = True
        safe_rerun()
    if col2.button("Dismiss", key=f"dc_dismiss_stale:{table_group_id}"):
        st.session_state[dismissed_key] = True
        safe_rerun()


# ---------------------------------------------------------------------------
# Save version dialog
# ---------------------------------------------------------------------------

@st.dialog("Regenerate Contract", width="small")
def _regenerate_dialog(table_group_id: str, current_version: int | None) -> None:
    """Re-export the contract from the live database and save it as a new version."""
    next_ver = (current_version + 1) if current_version is not None else 0
    st.markdown(f"**Re-export and save as Version {next_ver}**")
    st.caption(
        "This will re-generate the full contract YAML from the current database state "
        "(test definitions, profiling results, governance metadata) and save it as a new version. "
        "Any in-memory edits not yet saved will be discarded."
    )
    label = st.text_input("Label (optional)", placeholder="e.g. Regenerated with test descriptions")
    st.divider()
    go_col, cancel_col = st.columns(2)
    if go_col.button("Regenerate & Save", type="primary", use_container_width=True):
        with st.spinner("Exporting from database…"):
            import io as _io
            buf = _io.StringIO()
            _capture_yaml(table_group_id, buf)
            fresh_yaml = buf.getvalue()
        if not fresh_yaml.strip():
            st.error("Export produced no output — check that profiling and test suites exist.")
            return
        with st.spinner("Saving new version…"):
            new_version = save_contract_version(table_group_id, fresh_yaml, label or None)
        st.success(f"Saved as version {new_version}.")
        pending_key = f"dc_pending:{table_group_id}"
        yaml_key    = f"dc_yaml:{table_group_id}"
        version_key = f"dc_version:{table_group_id}"
        for k in (pending_key, yaml_key, version_key):
            st.session_state.pop(k, None)
        safe_rerun()
    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------

@st.dialog("Save New Version", width="small")
def _save_version_dialog(
    table_group_id: str,
    pending: dict,
    current_yaml: str,
    current_version: int | None,
) -> None:
    gov_edits = pending.get("governance", [])
    test_edits = pending.get("tests", [])
    next_ver = (current_version + 1) if current_version is not None else 0

    st.markdown(f"**Save as Version {next_ver}**")
    if current_version is not None:
        st.caption(f"Current latest: version {current_version}")

    if gov_edits or test_edits:
        st.markdown("**Changes to include:**")
        for e in gov_edits:
            st.markdown(f"  · {e['table']}.{e['col']} — {e['field']}: {e['value']}")
        for e in test_edits:
            st.markdown(f"  · Test `{e['rule_id'][:8]}…` updated")
    else:
        st.info("No edits pending — this will snapshot the current contract state without changes.", icon="ℹ️")

    label = st.text_input("Label (optional)", placeholder="e.g. Added PII tests for orders table")
    st.divider()
    save_col, cancel_col = st.columns(2)

    if save_col.button("Save Version", type="primary", use_container_width=True):
        from testgen.common.credentials import get_tg_schema
        from testgen.common.database.database_service import execute_db_queries
        schema = get_tg_schema()

        try:
            with st.spinner("Saving…"):
                # 1. Apply governance pending edits to DB
                for e in gov_edits:
                    field_map = {
                        "Classification": ("pii_flag", e["value"]),
                        "Description":    ("description", e["value"]),
                        "CDE":            ("critical_data_element", bool(e["value"])),
                    }
                    db_col, db_val = field_map.get(e["field"], (None, None))
                    if db_col:
                        execute_db_queries([(
                            f"UPDATE {schema}.data_column_chars SET {db_col} = :val "
                            "WHERE table_groups_id = :tg_id AND table_name = :tbl AND column_name = :col",
                            {"val": db_val, "tg_id": table_group_id, "tbl": e["table"], "col": e["col"]},
                        )])

                # 2. Apply test pending edits to DB
                for e in test_edits:
                    rule_id = e["rule_id"]
                    updates = {k: v for k, v in e.items() if k != "rule_id"}
                    if updates:
                        from testgen.commands.import_data_contract import _ALLOWED_TEST_COLS
                        safe_updates = {k: v for k, v in updates.items() if k in _ALLOWED_TEST_COLS}
                        if safe_updates:
                            params = {"test_id": rule_id, "lock_y": "Y"}
                            set_parts = []
                            for col, val in safe_updates.items():
                                params[f"p_{col}"] = val
                                set_parts.append(f"{col} = :p_{col}")
                            execute_db_queries([(
                                f"UPDATE {schema}.test_definitions SET {', '.join(set_parts)}, "
                                "last_manual_update = NOW(), lock_refresh = :lock_y WHERE id = :test_id",
                                params,
                            )])

                # 3. Save snapshot — use the current in-memory patched YAML (not a fresh export)
                new_version = save_contract_version(table_group_id, current_yaml, label or None)

            st.success(f"Saved as version {new_version}.")
            # Clear pending and force reload of new version
            pending_key = f"dc_pending:{table_group_id}"
            yaml_key = f"dc_yaml:{table_group_id}"
            version_key = f"dc_version:{table_group_id}"
            for k in (pending_key, yaml_key, version_key):
                st.session_state.pop(k, None)
            safe_rerun()

        except Exception as exc:
            st.error(f"Save failed: {exc}")

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# First-time flow renderer
# ---------------------------------------------------------------------------

def _render_first_time_flow(table_group_id: str) -> None:
    """Render the guided first-contract generation wizard."""
    prereqs = _check_contract_prerequisites(table_group_id)
    preview_key = f"dc_preview:{table_group_id}"
    in_preview = preview_key in st.session_state

    st.markdown("### No contract saved yet")
    st.caption("Generate your first contract by completing the steps below.")

    if not in_preview:
        # Step 1: prerequisites
        prof_ok = prereqs["has_profiling"]
        suite_ok = prereqs["has_suites"]

        st.markdown("**Before generating a contract we need:**")
        if prof_ok:
            last = prereqs["last_profiling"]
            last_str = last.strftime("%b %d, %Y") if last else ""
            st.success(f"✅  Profiling run complete   ({last_str})", icon=None)
        else:
            st.error("❌  No profiling run found — run profiling first.", icon=None)

        if suite_ok:
            st.success(f"✅  Test suites present   ({prereqs['suite_ct']} active tests, monitor suites excluded)", icon=None)
        else:
            st.error("❌  No non-monitor test suites with active tests found.", icon=None)

        meta_pct = prereqs["meta_pct"]
        if meta_pct < 25:
            st.warning(
                f"⚠️  Column metadata sparse ({meta_pct}% of columns have descriptions or PII flags). "
                "You can add these now or later — they improve contract coverage.",
                icon=None,
            )

        all_ok = prof_ok and suite_ok
        if st.button("Generate Contract Preview →", disabled=not all_ok, type="primary"):
            import io
            buf = io.StringIO()
            _capture_yaml(table_group_id, buf)
            st.session_state[preview_key] = buf.getvalue()
            safe_rerun()
    else:
        # Step 2: preview
        preview_yaml = st.session_state[preview_key]
        try:
            _parsed = yaml.safe_load(preview_yaml)
            preview_doc = _parsed if isinstance(_parsed, dict) else {}
        except yaml.YAMLError:
            preview_doc = {}

        st.info("📋 Contract preview — not yet saved", icon=None)
        anomalies: list[dict] = []
        _render_health_dashboard(preview_doc, anomalies, table_group_id)

        schema = preview_doc.get("schema") or []
        quality = preview_doc.get("quality") or []
        references = preview_doc.get("references") or []
        if schema:
            with st.expander("⚠️ Gap Analysis", expanded=True):
                _render_gap_analysis(schema, quality, references, anomalies)

        col1, col2 = st.columns([1, 3])
        if col1.button("← Back"):
            st.session_state.pop(preview_key, None)
            safe_rerun()

        if col2.button("Save as Version 0", type="primary"):
            _save_version_dialog(table_group_id, {}, preview_yaml, None)


# ---------------------------------------------------------------------------
# Review changes panel dialog
# ---------------------------------------------------------------------------

@st.dialog("Changes Since Last Save", width="large")
def _review_changes_panel(
    stale_diff: StaleDiff,
    table_group_id: str,
    version_record: dict,
    current_yaml: str,
) -> None:
    version_num = version_record.get("version", "?")
    saved_at = version_record.get("saved_at")
    saved_str = saved_at.strftime("%b %d, %Y at %H:%M") if saved_at else ""
    st.markdown(f"**Changes since version {version_num}** ({saved_str})")
    st.divider()

    def _section(title: str, items: list[dict], key_fn) -> None:
        if items:
            st.markdown(f"**{title}**")
            for item in items:
                icon = {"added": "➕", "removed": "➖", "changed": "✏️"}.get(item.get("change", ""), "·")
                st.markdown(f"{icon} {key_fn(item)}")
        else:
            st.markdown(f"**{title}** — no changes")

    _section(
        "Schema",
        stale_diff.schema_changes,
        lambda i: f"`{i['table']}.{i['column']}` {i.get('detail', '')}",
    )
    _section(
        "Quality rules",
        stale_diff.quality_changes,
        lambda i: f"`{i['element']}` {i['test_type']} {i.get('detail', '')} "
                  f"{'  (' + i['last_result'] + ')' if i.get('last_result') else ''}",
    )
    _section(
        "Governance",
        stale_diff.governance_changes,
        lambda i: f"`{i['table']}.{i['column']}` {i['field']} {i.get('detail', '')}",
    )
    _section(
        "Suite scope",
        stale_diff.suite_scope_changes,
        lambda i: f"{i['suite_name']}",
    )

    st.divider()
    close_col, save_col = st.columns([3, 1])
    if close_col.button("Close", use_container_width=True):
        safe_rerun()
    if save_col.button("Save new version →", type="primary", use_container_width=True):
        pending = st.session_state.get(f"dc_pending:{table_group_id}", {})
        _save_version_dialog(table_group_id, pending, current_yaml, version_record.get("version"))


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

class DataContractPage(Page):
    path = "data-contract"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "table_group_id" in st.query_params,
    ]
    menu_item = None

    def render(self, table_group_id: str, **_kwargs) -> None:
        from testgen.ui.components.widgets.testgen_component import testgen_component

        table_group = TableGroup.get_minimal(table_group_id)
        if not table_group:
            st.error("Table group not found.")
            return

        testgen.page_header(PAGE_TITLE, "connect-your-database/manage-table-groups/")

        # ── First-time flow ───────────────────────────────────────────────────
        if not has_any_version(table_group_id):
            _render_first_time_flow(table_group_id)
            return

        # ── Session state keys ────────────────────────────────────────────────
        yaml_key      = f"dc_yaml:{table_group_id}"
        version_key   = f"dc_version:{table_group_id}"
        pending_key   = f"dc_pending:{table_group_id}"
        anomaly_key   = f"dc_anomalies:{table_group_id}"

        # ── Version picker ────────────────────────────────────────────────────
        versions = list_contract_versions(table_group_id)
        requested_version: int | None = None
        raw_ver = st.query_params.get("version")
        if raw_ver is not None:
            try:
                requested_version = int(raw_ver)
            except ValueError:
                requested_version = None

        # Load or reload version record
        if version_key not in st.session_state or (
            requested_version is not None
            and st.session_state.get(version_key, {}).get("version") != requested_version
        ):
            record = load_contract_version(table_group_id, requested_version)
            if record is None:
                record = load_contract_version(table_group_id)
            st.session_state[version_key] = record
            st.session_state.pop(yaml_key, None)  # force YAML reload

        version_record: dict = st.session_state[version_key]
        is_latest = (version_record["version"] == versions[0]["version"]) if versions else True
        dismissed_key = f"dc_stale_dismissed:{table_group_id}:v{version_record['version']}"

        # Populate YAML from saved record (only once per version selection)
        if yaml_key not in st.session_state:
            st.session_state[yaml_key] = version_record["contract_yaml"]

        contract_yaml: str = st.session_state[yaml_key]
        pending: dict = st.session_state.get(pending_key, {})

        doc: dict = {}
        if contract_yaml:
            try:
                parsed = yaml.safe_load(contract_yaml)
                doc = parsed if isinstance(parsed, dict) else {}
            except yaml.YAMLError:
                doc = {}

        # ── Staleness check (latest version only) ─────────────────────────────
        stale_diff: StaleDiff | None = None
        if is_latest:
            tg_full = TableGroup.get(table_group_id)
            is_stale = bool(getattr(tg_full, "contract_stale", False))
            if is_stale and not st.session_state.get(dismissed_key):
                stale_diff = compute_staleness_diff(table_group_id, version_record["contract_yaml"])
                if stale_diff.is_empty:
                    mark_contract_not_stale(table_group_id)
                    stale_diff = None

        # ── Version picker UI + Save button (same row) ───────────────────────
        pending_ct = _pending_edit_count(pending)
        if len(versions) > 1:
            version_labels = [
                (
                    f"Version {v['version']}  ·  {v['saved_at'].strftime('%b %d %Y %H:%M') if v.get('saved_at') else ''}  "
                    f"{'— ' + v['label'] if v.get('label') else ''}  (latest)"
                    if i == 0 else
                    f"Version {v['version']}  ·  {v['saved_at'].strftime('%b %d %Y %H:%M') if v.get('saved_at') else ''}  "
                    f"{'— ' + v['label'] if v.get('label') else ''}"
                )
                for i, v in enumerate(versions)
            ]
            current_idx = next(
                (i for i, v in enumerate(versions) if v["version"] == version_record["version"]), 0
            )
            picker_col, regen_col, save_col = st.columns([4, 1, 1])
            with picker_col:
                chosen_idx = st.selectbox(
                    "Contract version",
                    options=range(len(versions)),
                    index=current_idx,
                    format_func=lambda i: version_labels[i],
                    label_visibility="collapsed",
                )
            if is_latest:
                with regen_col:
                    if st.button("↺ Regenerate", key=f"dc_regen_btn:{table_group_id}", use_container_width=True,
                                 help="Re-export from the database and save as a new version"):
                        _regenerate_dialog(table_group_id, version_record["version"])
                if pending_ct > 0:
                    pending_items = [
                        f"{e['table']}.{e['col']} {e['field']}" for e in pending.get("governance", [])
                    ] + [f"test {e['rule_id'][:8]}…" for e in pending.get("tests", [])]
                    tip = f"{pending_ct} unsaved change(s): " + "; ".join(pending_items[:3])
                    btn_label = f"Save new version ● ({pending_ct})"
                else:
                    tip = "Snapshot the current contract state as a new version"
                    btn_label = "Save new version"
                with save_col:
                    if st.button(btn_label, type="secondary", help=tip, key=f"dc_save_btn:{table_group_id}", use_container_width=True):
                        _save_version_dialog(table_group_id, pending, contract_yaml, version_record["version"])
            if chosen_idx != current_idx:
                chosen_ver = versions[chosen_idx]["version"]
                if pending and _pending_edit_count(pending) > 0:
                    st.warning("You have unsaved changes. Switch versions? Changes will be lost.")
                    c1, c2 = st.columns(2)
                    if c1.button("Switch anyway"):
                        st.session_state.pop(pending_key, None)
                        st.session_state.pop(yaml_key, None)
                        st.session_state.pop(version_key, None)
                        st.query_params["version"] = str(chosen_ver)
                        safe_rerun()
                    if c2.button("Stay"):
                        safe_rerun()
                else:
                    st.session_state.pop(yaml_key, None)
                    st.session_state.pop(version_key, None)
                    st.query_params["version"] = str(chosen_ver)
                    safe_rerun()
        elif is_latest:
            # No version picker (only one version) — regen + save buttons float right
            _, regen_col, save_col = st.columns([4, 1, 1])
            with regen_col:
                if st.button("↺ Regenerate", key=f"dc_regen_btn:{table_group_id}", use_container_width=True,
                             help="Re-export from the database and save as a new version"):
                    _regenerate_dialog(table_group_id, version_record["version"])
            if pending_ct > 0:
                pending_items = [
                    f"{e['table']}.{e['col']} {e['field']}" for e in pending.get("governance", [])
                ] + [f"test {e['rule_id'][:8]}…" for e in pending.get("tests", [])]
                tip = f"{pending_ct} unsaved change(s): " + "; ".join(pending_items[:3])
                btn_label = f"Save new version ● ({pending_ct})"
            else:
                tip = "Snapshot the current contract state as a new version"
                btn_label = "Save new version"
            with save_col:
                if st.button(btn_label, type="secondary", help=tip, key=f"dc_save_btn:{table_group_id}", use_container_width=True):
                    _save_version_dialog(table_group_id, pending, contract_yaml, version_record["version"])

        # ── Historic read-only banner ─────────────────────────────────────────
        if not is_latest:
            saved_at = version_record.get("saved_at")
            saved_str = saved_at.strftime("%b %d, %Y at %H:%M") if saved_at else ""
            label_str = f' "{version_record["label"]}"' if version_record.get("label") else ""
            st.info(
                f"📋 Viewing version {version_record['version']}{label_str} — saved {saved_str}. "
                f"This is a read-only snapshot. The latest is version {versions[0]['version']}.",
                icon=None,
            )

        # ── Staleness banner (latest only) ────────────────────────────────────
        if stale_diff and is_latest:
            _render_staleness_banner(version_record, stale_diff, table_group_id, dismissed_key)

        # ── Review changes panel ──────────────────────────────────────────────
        if st.session_state.pop(f"dc_show_review:{table_group_id}", False) and stale_diff:
            _review_changes_panel(stale_diff, table_group_id, version_record, contract_yaml)

        # ── Anomalies ─────────────────────────────────────────────────────────
        if anomaly_key not in st.session_state:
            st.session_state[anomaly_key] = _fetch_anomalies(table_group_id)
        anomalies: list[dict] = st.session_state[anomaly_key]

        run_dates    = _fetch_last_run_dates(table_group_id)
        suite_scope  = _fetch_suite_scope(table_group_id)
        test_statuses = _fetch_test_statuses(table_group_id)
        props = _build_contract_props(table_group, doc, anomalies, contract_yaml, run_dates, suite_scope, test_statuses)

        # Pass versioning state to VanJS
        props["version_info"] = {
            "version": version_record["version"],
            "saved_at": version_record["saved_at"].isoformat() if version_record.get("saved_at") else None,
            "label": version_record.get("label"),
            "is_latest": is_latest,
            "is_stale": stale_diff is not None,
            "pending_count": pending_ct,
        }

        # ── Event handlers ────────────────────────────────────────────────────
        def on_refresh(_payload: object) -> None:
            if pending_ct > 0:
                st.warning("You have unsaved changes. Refresh will discard them.")
                # In practice the user can use the browser; this is a best-effort guard
            st.session_state.pop(yaml_key, None)
            st.session_state.pop(anomaly_key, None)
            st.session_state.pop(version_key, None)
            st.session_state.pop(pending_key, None)
            safe_rerun()

        def on_suite_picker(_payload: object) -> None:
            suite_runs = props.get("health", {}).get("suite_runs", [])
            if suite_runs:
                _suite_picker_dialog(suite_runs)

        def on_claim_detail(payload: dict) -> None:
            claim      = payload.get("claim", {})
            table_name = payload.get("tableName", "")
            col_name   = payload.get("colName", "")
            source = claim.get("source", "")
            verif  = claim.get("verif", "")
            claim_name = claim.get("name", "")
            if not is_latest:
                _claim_read_dialog(claim, table_name, col_name, table_group_id, yaml_key)
            elif source == "monitor":
                _monitor_claim_dialog(claim.get("rule", {}), claim_name, table_name, col_name)
            elif source == "test":
                _project_code = getattr(table_group, "project_code", "")
                _test_claim_dialog(claim, table_name, col_name, _project_code)
            elif source == "governance" and verif == "declared":
                _claim_edit_dialog(claim, table_name, col_name, table_group_id, yaml_key)
            else:
                _claim_read_dialog(claim, table_name, col_name, table_group_id, yaml_key)

        def on_governance_edit(payload: dict) -> None:
            col_id     = payload.get("columnId", "")
            table_name = payload.get("tableName", "")
            col_name   = payload.get("colName", "")
            if not is_latest:
                return
            # If column_id wasn't in props, look it up now
            if not col_id:
                col_id = _lookup_column_id(table_group_id, table_name, col_name)
            _governance_edit_dialog(col_id, table_name, col_name, table_group_id, yaml_key)

        def on_edit_rule(payload: dict) -> None:
            if not is_latest:
                return
            rule_id = str(payload.get("rule_id", ""))
            rule = next(
                (r for r in (doc.get("quality") or []) if str(r.get("id", "")) == rule_id),
                None,
            )
            if rule:
                _edit_rule_dialog(rule, table_group_id, yaml_key)

        testgen_component(
            "data_contract",
            props=props,
            event_handlers={
                "RefreshClicked":        on_refresh,
                "EditRuleClicked":       on_edit_rule,
                "ClaimDetailClicked":    on_claim_detail,
                "SuitePickerClicked":    on_suite_picker,
                "GovernanceEditClicked": on_governance_edit,
            },
        )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@with_database_session
def _capture_yaml(table_group_id: str, buf: io.StringIO) -> None:
    import sys
    old = sys.stdout
    sys.stdout = buf
    try:
        run_export_data_contract(table_group_id, output_path=None)
    finally:
        sys.stdout = old


@with_database_session
def _fetch_anomalies(table_group_id: str) -> list[dict]:
    schema = get_tg_schema()
    sql = f"""
        SELECT
            r.table_name,
            r.column_name,
            t.anomaly_type,
            t.anomaly_name,
            t.anomaly_description,
            t.issue_likelihood,
            t.dq_dimension,
            t.suggested_action,
            r.detail,
            r.disposition
        FROM {schema}.profile_anomaly_results r
        INNER JOIN {schema}.profile_anomaly_types t ON r.anomaly_id = t.id
        WHERE r.table_groups_id = '{table_group_id}'
          AND r.profile_run_id = (
              SELECT id FROM {schema}.profiling_runs
              WHERE  table_groups_id = '{table_group_id}'
                AND  status = 'Complete'
              ORDER  BY profiling_starttime DESC
              LIMIT  1
          )
          AND COALESCE(r.disposition, 'Confirmed') != 'Inactive'
        ORDER BY
            CASE t.issue_likelihood
                WHEN 'Definite' THEN 1 WHEN 'Likely' THEN 2 WHEN 'Possible' THEN 3 ELSE 4
            END,
            r.table_name, r.column_name
    """
    try:
        return [dict(row) for row in fetch_dict_from_db(sql)]
    except Exception:
        LOG.warning("_fetch_anomalies failed for tg_id=%s", table_group_id, exc_info=True)
        return []


@with_database_session
def _fetch_suite_scope(table_group_id: str) -> dict:
    """Return which test suites are included/excluded from the contract."""
    schema = get_tg_schema()
    sql = f"""
        SELECT test_suite, COALESCE(include_in_contract, TRUE) AS include_in_contract
        FROM {schema}.test_suites
        WHERE table_groups_id = :tg_id
          AND is_monitor IS NOT TRUE
        ORDER BY LOWER(test_suite)
    """
    try:
        rows = fetch_dict_from_db(sql, params={"tg_id": table_group_id})
        included = [r["test_suite"] for r in rows if r["include_in_contract"]]
        excluded = [r["test_suite"] for r in rows if not r["include_in_contract"]]
        return {"included": included, "excluded": excluded, "total": len(rows)}
    except Exception:
        LOG.warning("_fetch_suite_scope failed for tg_id=%s", table_group_id, exc_info=True)
        return {"included": [], "excluded": [], "total": 0}


@with_database_session
def _fetch_governance_data(table_group_id: str) -> dict[tuple[str, str], dict]:
    """Return governance metadata keyed by (table_name, col_name) from data_column_chars."""
    schema = get_tg_schema()
    sql = f"""
        SELECT
            column_id::text AS column_id,
            table_name,
            column_name,
            critical_data_element,
            excluded_data_element,
            pii_flag,
            description,
            data_source,
            source_system,
            source_process,
            business_domain,
            stakeholder_group,
            transform_level,
            aggregation_level,
            data_product
        FROM {schema}.data_column_chars
        WHERE table_groups_id = :tg_id
    """
    try:
        rows = fetch_dict_from_db(sql, params={"tg_id": table_group_id})
        return {(r["table_name"], r["column_name"]): dict(r) for r in (rows or [])}
    except Exception:
        LOG.warning("_fetch_governance_data failed for tg_id=%s", table_group_id, exc_info=True)
        return {}


@with_database_session
def _lookup_column_id(table_group_id: str, table_name: str, col_name: str) -> str:
    """Return the column_id UUID string for a given table/column, or '' if not found."""
    schema = get_tg_schema()
    sql = f"""
        SELECT column_id::text AS column_id
        FROM {schema}.data_column_chars
        WHERE table_groups_id = :tg_id
          AND table_name = :tbl
          AND column_name = :col
        LIMIT 1
    """
    try:
        rows = fetch_dict_from_db(sql, params={"tg_id": table_group_id, "tbl": table_name, "col": col_name})
        return (rows[0]["column_id"] or "") if rows else ""
    except Exception:
        LOG.warning("_lookup_column_id failed", exc_info=True)
        return ""


@with_database_session
def _save_governance_data(column_id: str, updates: dict) -> None:
    """Persist governance field updates to data_column_chars."""
    schema = get_tg_schema()
    set_clauses = []
    params: dict = {"col_id": column_id}
    bool_fields = {"critical_data_element", "excluded_data_element"}
    for key, val in updates.items():
        if key in bool_fields:
            set_clauses.append(f"{key} = :{key}")
            params[key] = val
        elif key == "pii_flag":
            set_clauses.append(f"{key} = :{key}")
            params[key] = val  # None or string
        else:
            set_clauses.append(f"{key} = NULLIF(:{key}, '')")
            params[key] = val or ""
    if not set_clauses:
        return
    sql = (
        f"UPDATE {schema}.data_column_chars "
        f"SET {', '.join(set_clauses)} "
        f"WHERE column_id = CAST(:col_id AS uuid)"
    )
    execute_db_queries([(sql, params)])


@with_database_session
def _fetch_test_live_info(test_def_id: str) -> dict:
    """Return live suite_id, status, last run timestamp, test name, and descriptions."""
    schema = get_tg_schema()
    sql = f"""
        SELECT
            td.test_suite_id::text          AS suite_id,
            td.test_description             AS user_description,
            tt.test_name_short,
            tt.test_name_long,
            tt.test_description             AS type_description,
            tr.result_status,
            tr.test_time
        FROM {schema}.test_definitions td
        LEFT JOIN {schema}.test_types tt ON tt.test_type = td.test_type
        LEFT JOIN LATERAL (
            SELECT result_status, test_time
            FROM   {schema}.test_results
            WHERE  test_definition_id = td.id
              AND  disposition IS DISTINCT FROM 'Inactive'
            ORDER  BY test_time DESC
            LIMIT  1
        ) tr ON TRUE
        WHERE td.id = :tid
        LIMIT 1
    """
    try:
        rows = fetch_dict_from_db(sql, params={"tid": test_def_id})
        if not rows:
            return {}
        row = dict(rows[0])
        status_map = {"Passed": "passing", "Failed": "failing", "Warning": "warning", "Error": "error"}
        return {
            "suite_id":         row.get("suite_id") or "",
            "status":           status_map.get(row.get("result_status") or "", "") or "",
            "test_time":        row.get("test_time"),
            "test_name_short":  row.get("test_name_short") or "",
            "test_name_long":   row.get("test_name_long") or "",
            "user_description": row.get("user_description") or "",
            "type_description": row.get("type_description") or "",
        }
    except Exception:
        LOG.warning("_fetch_test_live_info failed for test_def_id=%s", test_def_id, exc_info=True)
        return {}


@with_database_session
def _fetch_test_statuses(table_group_id: str) -> dict[str, str]:
    """Return {test_def_id: odcs_status} for the latest result of every active test in the contract."""
    schema = get_tg_schema()
    sql = f"""
        SELECT DISTINCT ON (td.id)
            td.id::text                                                           AS test_def_id,
            CASE tr.result_status
                WHEN 'Passed'  THEN 'passing'
                WHEN 'Failed'  THEN 'failing'
                WHEN 'Warning' THEN 'warning'
                WHEN 'Error'   THEN 'error'
                ELSE NULL
            END                                                                   AS status
        FROM {schema}.test_definitions td
        JOIN {schema}.test_suites s      ON s.id  = td.test_suite_id
        LEFT JOIN {schema}.test_results tr ON tr.test_definition_id = td.id
                                          AND tr.disposition IS DISTINCT FROM 'Inactive'
        WHERE s.table_groups_id        = :tg_id
          AND s.include_in_contract    IS NOT FALSE
          AND COALESCE(s.is_monitor, FALSE) = FALSE
          AND td.test_active           = 'Y'
        ORDER BY td.id, tr.test_time DESC NULLS LAST
    """
    try:
        rows = fetch_dict_from_db(sql, params={"tg_id": table_group_id})
        return {r["test_def_id"]: r["status"] for r in (rows or []) if r["status"]}
    except Exception:
        _log.exception("_fetch_test_statuses failed for tg_id=%s", table_group_id)
        return {}


@with_database_session
def _fetch_last_run_dates(table_group_id: str) -> dict:
    schema = get_tg_schema()

    # Per-suite: latest test run for every included suite that has runs.
    # Uses DISTINCT ON so each suite contributes at most one row (no LATERAL needed).
    # Monitor suites are included so we always have a navigation target, but are
    # marked so they can be filtered out of the picker display.
    suite_sql = f"""
        SELECT
            suite_id,
            suite_name,
            is_monitor,
            run_id,
            run_start,
            test_ct,
            passed_ct,
            warning_ct,
            failed_ct,
            error_ct
        FROM (
            SELECT DISTINCT ON (s.id)
                s.id::text                    AS suite_id,
                s.test_suite                  AS suite_name,
                COALESCE(s.is_monitor, FALSE) AS is_monitor,
                tr.id::text                   AS run_id,
                tr.test_starttime             AS run_start,
                COALESCE(tr.test_ct,    0)    AS test_ct,
                COALESCE(tr.passed_ct,  0)    AS passed_ct,
                COALESCE(tr.warning_ct, 0)    AS warning_ct,
                COALESCE(tr.failed_ct,  0)    AS failed_ct,
                COALESCE(tr.error_ct,   0)    AS error_ct
            FROM {schema}.test_suites s
            JOIN {schema}.test_runs tr ON tr.test_suite_id = s.id
            WHERE s.table_groups_id = :tg_id
              AND s.include_in_contract IS NOT FALSE
            ORDER BY s.id, tr.test_starttime DESC
        ) latest
        ORDER BY is_monitor ASC, run_start DESC
    """

    # Latest completed profiling run for this table group.
    profiling_sql = f"""
        SELECT id, profiling_starttime
        FROM {schema}.profiling_runs
        WHERE table_groups_id = :tg_id
          AND status = 'Complete'
        ORDER BY profiling_starttime DESC
        LIMIT 1
    """

    try:
        suite_rows = fetch_dict_from_db(suite_sql, params={"tg_id": table_group_id})
        pr_rows = fetch_dict_from_db(profiling_sql, params={"tg_id": table_group_id})
    except Exception:
        _log.exception("_fetch_last_run_dates failed for tg_id=%s", table_group_id)
        return {}

    all_runs = [dict(r) for r in (suite_rows or [])]

    # Picker shows only non-monitor suites; monitors are excluded from count/display.
    suite_runs = [r for r in all_runs if not r.get("is_monitor")]
    _log.info("_fetch_last_run_dates: tg_id=%s all_runs=%d suite_runs=%d totals=%s",
              table_group_id, len(all_runs), len(suite_runs),
              [(r["suite_name"], r.get("test_ct")) for r in suite_runs])

    # For navigation, prefer the latest non-monitor run; fall back to any run.
    nav_run = (suite_runs or all_runs or [None])[0]

    result: dict = {
        "suite_runs": suite_runs,
        "last_profiling_run_id": None,
        "last_profiling_run": None,
        "last_test_run_id":  nav_run["run_id"]    if nav_run else None,
        "last_test_run":     nav_run["run_start"] if nav_run else None,
    }

    if pr_rows:
        pr = dict(pr_rows[0])
        result["last_profiling_run_id"] = str(pr["id"]) if pr.get("id") else None
        result["last_profiling_run"] = pr.get("profiling_starttime")

    return result



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


