"""
Data Contract UI view — ODCS v3.1.0

Health dashboard · Coverage matrix · Gap analysis · Claims detail with inline editing.
"""
from __future__ import annotations

import io
import logging
import re
import typing

_log = logging.getLogger(__name__)

import streamlit as st
import yaml

from testgen.commands.export_data_contract import run_export_data_contract
from testgen.commands.import_data_contract import ContractDiff, run_import_data_contract
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

_STATUS_COLOR: dict[str, str] = {
    "active": "green",
    "proposed": "blue",
    "draft": "orange",
    "deprecated": "red",
    "retired": "gray",
}

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

_TIERS: dict[str, tuple[str, str, str]] = {
    "db_enforced": ("🏛️", "Database Schema Enforced",
                    "The database DDL itself rejects violations at write time — no test needed"),
    "tested":      ("⚡", "Tested",
                    "An active quality test checks this on every test run — hard pass/fail result"),
    "monitored":   ("🔬", "Hygiene Monitored",
                    "A profile anomaly detector fires during profiling runs — flagged but not blocking"),
    "observed":    ("📸", "Observed",
                    "Captured from profiling statistics — a snapshot of what we saw, not what we're watching"),
    "declared":    ("🏷️", "Declared",
                    "Manually annotated governance metadata — not derived from or checked against the data"),
}

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


def _render_tier_legend() -> None:
    parts = "  ".join(f"{icon} **{name}**" for icon, name, _ in _TIERS.values())
    st.caption(f"Coverage legend: {parts}")


def _render_tier_legend_full() -> None:
    st.markdown("### Enforcement Coverage Legend")
    for _key, (icon, name, desc) in _TIERS.items():
        st.markdown(f"**{icon} {name}** — {desc}")


# ---------------------------------------------------------------------------
# Claim card infrastructure — improvement #5: left-border stripe + single badge
# ---------------------------------------------------------------------------

_SOURCE_META: dict[str, tuple[str, str, str]] = {
    # key: (display label, card background, left-border color)
    "ddl":        ("DDL",        "#f3f0fa", "#7c4dff"),
    "profiling":  ("Profiling",  "#e8f4fd", "#1976d2"),
    "governance": ("Governance", "#fffde7", "#ffa000"),
    "test":       ("Test",       "#f1f8e9", "#388e3c"),
}

_VERIF_META: dict[str, tuple[str, str, str]] = {
    # key: (icon, display label, badge color)
    "db_enforced": ("🏛️", "DB Enforced", "#283593"),
    "tested":      ("⚡", "Tested",       "#1b5e20"),
    "monitored":   ("🔬", "Monitored",    "#e65100"),
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
    name_esc = claim["name"].replace("<", "&lt;").replace(">", "&gt;")
    val_esc = claim["value"].replace("<", "&lt;").replace(">", "&gt;")
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


def _render_contract_legend() -> None:
    border_swatches = "&nbsp;&nbsp;".join(
        f'<span style="display:inline-block;width:8px;height:14px;background:{border};'
        f'border-radius:2px;vertical-align:middle;margin-right:3px;"></span>'
        f'<span style="font-size:11px;color:#444;">{label}</span>'
        for label, _, border in _SOURCE_META.values()
    )
    verif_pills = "&nbsp;".join(
        f'<span style="font-size:10px;background:{badge};color:#fff;'
        f'border-radius:3px;padding:1px 6px;">{icon} {label}</span>'
        for icon, label, badge in _VERIF_META.values()
    )
    st.markdown(
        f"<div style='margin-bottom:10px;line-height:2;'>"
        f"<strong style='font-size:11px;'>Border&nbsp;(source):</strong>&nbsp; {border_swatches}"
        f"&nbsp;&nbsp;&nbsp;&nbsp;"
        f"<strong style='font-size:11px;'>Badge&nbsp;(verification):</strong>&nbsp; {verif_pills}"
        f"</div>",
        unsafe_allow_html=True,
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

    if active:
        st.info(
            f"Filter active: **{active}** — showing only matching columns. "
            "Click the button above to clear.",
            icon=":material/filter_alt:",
        )


# ---------------------------------------------------------------------------
# Improvement #2 — Coverage matrix
# ---------------------------------------------------------------------------

def _test_cell(counts: dict[str, int], n: int) -> str:
    if n == 0:
        return ""
    worst = _worst_status(counts)
    icon = _STATUS_ICON.get(worst, "⏳")
    return f"{icon} {n}"


def _anomaly_cell(col_anomalies: list[dict]) -> str:
    if not col_anomalies:
        return ""
    worst = "Possible"
    for a in col_anomalies:
        lk = a.get("issue_likelihood", "")
        if lk == "Definite":
            worst = "Definite"
            break
        if lk == "Likely":
            worst = "Likely"
    icon = {"Definite": "❌", "Likely": "⚠️", "Possible": "🔵"}.get(worst, "⚠️")
    return f"{icon} {len(col_anomalies)}"


def _render_coverage_matrix(
    schema: list[dict],
    quality: list[dict],
    references: list[dict],
    anomalies: list[dict],
    active_filter: str | None,
) -> None:
    rules_by_element, anomalies_by_col, refs_by_col = _build_lookups(quality, references, anomalies)
    matrix: list[dict] = []

    for table in schema:
        table_name = table.get("name", "")
        for prop in (table.get("properties") or []):
            col_name = prop.get("name", "")
            col_key = f"{table_name}.{col_name}"
            opts = prop.get("logicalTypeOptions") or {}

            col_rules = rules_by_element.get(col_key, []) + rules_by_element.get(col_name, [])
            col_anomalies = anomalies_by_col.get((table_name, col_name), [])
            col_refs = refs_by_col.get(col_key, []) + refs_by_col.get(col_name, [])

            test_counts = _quality_counts(col_rules)
            worst_test = _worst_status(test_counts) if col_rules else None
            has_failing = worst_test in ("failing", "error")
            has_anomaly = bool(col_anomalies)
            has_any_nontrivial = bool(
                col_rules
                or prop.get("classification")
                or prop.get("criticalDataElement")
                or prop.get("description")
                or opts.get("format")
            )

            if active_filter == "uncovered" and has_any_nontrivial:
                continue
            if active_filter == "failing" and not has_failing:
                continue
            if active_filter == "anomalies" and not has_anomaly:
                continue

            key_cell = "🔑 PK" if opts.get("primaryKey") else ("🔗 FK" if col_refs else "")

            matrix.append({
                "Table": table_name,
                "Column": col_name,
                "Type": prop.get("physicalType") or "",
                "Not Null": "Req" if (prop.get("required") or prop.get("nullable") is False) else "",
                "Key": key_cell,
                "Tests": _test_cell(test_counts, len(col_rules)),
                "Anomaly": _anomaly_cell(col_anomalies),
                "Class": prop.get("classification") or "",
                "CDE": "★" if prop.get("criticalDataElement") else "",
            })

    if not matrix:
        msg = "No columns match the current filter." if active_filter else "No schema data available."
        st.info(msg)
        return

    st.dataframe(matrix, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Improvement #3 — Gap analysis
# ---------------------------------------------------------------------------

def _render_gap_analysis(
    schema: list[dict],
    quality: list[dict],
    references: list[dict],
    anomalies: list[dict],
) -> None:
    rules_by_element, _, _ = _build_lookups(quality, references, anomalies)
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    for table in schema:
        table_name = table.get("name", "")
        table_has_tests = False

        for prop in (table.get("properties") or []):
            col_name = prop.get("name", "")
            col_key = f"{table_name}.{col_name}"
            col_rules = rules_by_element.get(col_key, []) + rules_by_element.get(col_name, [])
            opts = prop.get("logicalTypeOptions") or {}

            if col_rules:
                table_has_tests = True

            cls = (prop.get("classification") or "").lower()
            if cls in ("pii", "sensitive", "restricted") and not col_rules:
                errors.append(f"`{table_name}.{col_name}` classified **{prop['classification']}** but has no quality test")

            if prop.get("criticalDataElement") and not col_rules:
                warnings.append(f"`{table_name}.{col_name}` is a **Critical Data Element** with no test enforcing it")

            has_range = opts.get("minimum") is not None or opts.get("maximum") is not None
            range_ops = ("mustBe", "mustBeGreaterThan", "mustBeGreaterOrEqualTo",
                         "mustBeLessThan", "mustBeLessOrEqualTo", "mustBeBetween")
            has_range_test = any(op in r for r in col_rules for op in range_ops)
            if has_range and not has_range_test:
                infos.append(f"`{table_name}.{col_name}` has observed min/max but no range test is configured")

            if not prop.get("description"):
                infos.append(f"`{table_name}.{col_name}` has no description (governance gap)")

        if not table_has_tests:
            warnings.append(f"Table **{table_name}** has no quality tests of any kind")

    if not errors and not warnings and not infos:
        st.success("No contract gaps detected.", icon=":material/check_circle:")
        return

    for msg in errors:
        st.error(msg, icon=":material/error:")
    for msg in warnings:
        st.warning(msg, icon=":material/warning:")

    if infos:
        if st.toggle(f"Show {len(infos)} informational gap(s)", key="dc_show_info_gaps"):
            for msg in infos:
                st.info(msg, icon=":material/info:")


# ---------------------------------------------------------------------------
# Improvement #4 — Static vs live split  +  #5 — border-stripe cards
# ---------------------------------------------------------------------------

def _extract_column_claims(
    prop: dict,
    col_rules: list[dict],
    col_anomalies: list[dict],
    col_refs: list[dict],
) -> list[dict]:
    claims: list[dict] = []
    opts = prop.get("logicalTypeOptions") or {}
    physical = (prop.get("physicalType") or "").strip()
    physical_lower = physical.lower()
    base = physical_lower.split("(")[0].strip()

    # --- Static claims (schema + governance + profiling observations) ---
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

    if prop.get("classification"):
        claims.append(_claim("Classification", prop["classification"], "governance", "declared", kind="static"))

    if prop.get("criticalDataElement"):
        claims.append(_claim("CDE", "Critical", "governance", "declared", kind="static"))

    if prop.get("description"):
        full_desc = str(prop["description"])
        desc = full_desc if len(full_desc) <= 45 else full_desc[:42] + "…"
        claims.append(_claim("Description", desc, "governance", "declared", kind="static",
                              full_value=full_desc))

    if opts.get("minimum") is not None:
        claims.append(_claim("Min Value", opts["minimum"], "profiling", "observed", kind="static"))
    if opts.get("maximum") is not None:
        claims.append(_claim("Max Value", opts["maximum"], "profiling", "observed", kind="static"))
    if opts.get("minLength") is not None:
        claims.append(_claim("Min Length", opts["minLength"], "profiling", "observed", kind="static"))
    if opts.get("maxLength") is not None:
        verif = "monitored" if _CHAR_CONSTRAINED_RE.match(physical_lower) else "observed"
        claims.append(_claim("Max Length", opts["maxLength"], "profiling", verif, kind="static"))
    if opts.get("format"):
        claims.append(_claim("Format", opts["format"], "profiling", "observed", kind="static"))
    if prop.get("logicalType"):
        claims.append(_claim("Logical Type", prop["logicalType"], "profiling", "observed", kind="static"))

    # --- Live claims (tests + anomalies) ---
    for rule in col_rules:
        test_name = rule.get("name") or rule.get("type") or rule.get("testType") or "Test"
        last = rule.get("lastResult") or {}
        status = last.get("status") or "not run"
        status_icon = _STATUS_ICON.get(status, "⏳")
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
            "profiling", "monitored",
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
            is_test = claim.get("name") == "Test"
            status = claim.get("status", "not run")
            border_color = (
                "#c62828" if status in ("failing", "error") else
                "#f9a825" if status == "warning" or claim.get("name") == "Hygiene" else
                "#2e7d32" if status == "passing" else
                "#90a4ae"
            )
            st.markdown(
                f'<div style="border:1px solid #e0e0e0;border-left:4px solid {border_color};'
                f'border-radius:0 6px 6px 0;padding:7px 10px;background:#fafafa;">'
                f'<div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:0.5px;">'
                f'{"Test" if is_test else "Hygiene"}</div>'
                f'<div style="font-size:12px;font-weight:600;color:#1a1a1a;word-break:break-word;'
                f'margin:2px 0 0 0;">{claim["value"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if is_test and claim.get("rule"):
                rule = claim["rule"]
                rule_id = str(rule.get("id", ""))
                if rule_id:
                    btn_key = f"edit_{col_key}_{rule_id[:8]}_{i}"
                    if st.button("✏️ Edit", key=btn_key, type="tertiary", use_container_width=True):
                        _edit_rule_dialog(rule, table_group_id, yaml_key)


def _render_schema_claims(
    schema: list[dict],
    quality: list[dict],
    references: list[dict],
    anomalies: list[dict],
    table_group_id: str,
    yaml_key: str,
    active_filter: str | None = None,
) -> None:
    rules_by_element, anomalies_by_col, refs_by_col = _build_lookups(quality, references, anomalies)

    for table in schema:
        table_name = table.get("name", "")
        props = table.get("properties") or []

        # Table-level rules: element matches the table name exactly
        table_rules = rules_by_element.get(table_name, [])

        with st.expander(f"**{table_name}** — {len(props)} column(s)", expanded=True):
            if table_rules:
                live_table = [
                    _claim(
                        "Test",
                        f"{_STATUS_ICON.get((r.get('lastResult') or {}).get('status') or 'not run', '⏳')} "
                        f"{r.get('name') or r.get('type') or 'Test'}",
                        "test", "tested",
                        kind="live", rule=r,
                        status=(r.get("lastResult") or {}).get("status") or "not run",
                    )
                    for r in table_rules
                ]
                st.markdown(
                    '<div style="font-size:11px;font-style:italic;color:#777;margin:6px 0 2px 0;">'
                    'table-level</div>',
                    unsafe_allow_html=True,
                )
                _render_live_claims_row(f"tbl_{table_name}", live_table, table_group_id, yaml_key)

            for prop in props:
                col_name = prop.get("name", "")
                col_key = f"{table_name}.{col_name}"
                col_rules = rules_by_element.get(col_key, []) + rules_by_element.get(col_name, [])
                col_anomalies = anomalies_by_col.get((table_name, col_name), [])
                col_refs = refs_by_col.get(col_key, []) + refs_by_col.get(col_name, [])

                claims = _extract_column_claims(prop, col_rules, col_anomalies, col_refs)
                if not claims:
                    continue

                static_claims = [c for c in claims if c.get("kind") == "static"]
                live_claims = [c for c in claims if c.get("kind") == "live"]

                # Apply active filter
                has_failing = any(c.get("status") in ("failing", "error") for c in live_claims)
                has_anomaly = any(c.get("name") == "Hygiene" for c in live_claims)
                has_nontrivial = bool(
                    col_rules
                    or prop.get("classification")
                    or prop.get("criticalDataElement")
                    or prop.get("description")
                    or (prop.get("logicalTypeOptions") or {}).get("format")
                )
                if active_filter == "uncovered" and has_nontrivial:
                    continue
                if active_filter == "failing" and not has_failing:
                    continue
                if active_filter == "anomalies" and not has_anomaly:
                    continue

                # Column header with inline status indicator
                indicator = " ❌" if has_failing else (" ⚠️" if has_anomaly else "")
                st.markdown(
                    f'<div style="margin:12px 0 4px 0;font-size:13px;font-weight:600;color:#333;">'
                    f'▸ {col_name}{indicator}'
                    f'<span style="font-size:11px;font-weight:400;color:#999;margin-left:8px;">'
                    f'{len(static_claims)} static · {len(live_claims)} live</span></div>',
                    unsafe_allow_html=True,
                )

                if static_claims:
                    cards_html = "".join(_claim_card_html(c) for c in static_claims)
                    st.markdown(
                        f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px;">'
                        f'{cards_html}</div>',
                        unsafe_allow_html=True,
                    )

                if live_claims:
                    _render_live_claims_row(col_key, live_claims, table_group_id, yaml_key)


# ---------------------------------------------------------------------------
# Improvement #6 — Inline editing dialog
# ---------------------------------------------------------------------------

_SRC_LABEL = {"ddl": "DDL", "profiling": "Profiling", "governance": "Governance", "test": "Test"}
_VERIF_LABEL = {
    "db_enforced": "🏛️ DB Enforced",
    "tested":      "⚡ Tested",
    "monitored":   "🔬 Monitored",
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
        doc["references"] = [
            r for r in refs
            if r.get("from") not in (col_key, col_name)
        ]
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


@st.dialog("Test Claim Detail", width="small")
def _test_claim_dialog(claim: dict, table_name: str, col_name: str) -> None:
    status = claim.get("status", "")
    status_icon = _STATUS_ICON.get(status, "⏳")
    test_name = claim.get("test_name") or "Test"
    element = claim.get("element") or f"{table_name}.{col_name}"
    dimension = claim.get("dimension", "")
    severity = claim.get("severity", "")

    st.markdown(f"**{test_name}**")
    st.caption(f"{table_name} › `{col_name}`")
    st.divider()

    col1, col2 = st.columns(2)
    col1.markdown(f"**Status**  \n{status_icon} {status.title() if status else 'Not Run'}")
    if element:
        col2.markdown(f"**Element**  \n`{element}`")
    if dimension or severity:
        c1, c2 = st.columns(2)
        if dimension:
            c1.markdown(f"**Dimension**  \n{dimension.title()}")
        if severity:
            c2.markdown(f"**Severity**  \n{severity.title()}")

    st.caption("Managed in TestGen test suites. To edit thresholds or run it, go to Test Suites.")
    st.divider()
    if st.button("Close", key="test_claim_close", use_container_width=True):
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

    st.markdown(f"**{claim_name}**")
    st.caption(
        f"{table_name} › `{col_name}` · "
        f"{_SRC_LABEL.get(src, src)} · {_VERIF_LABEL.get(verif, verif)}"
    )
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
                doc = yaml.safe_load(current_yaml) or {}
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

    st.caption(f"{table_name} › `{col_name}` · 🏷️ Declared governance metadata")

    if claim_name == "CDE":
        new_cde: bool = st.checkbox("Mark as Critical Data Element", value=True)
        new_value: str = "true" if new_cde else ""
    elif claim_name == "Description":
        new_value = st.text_area("Description", value=current_value, height=120)
    else:
        new_value = st.text_input(claim_name, value=current_value)

    st.divider()
    save_col, cancel_col = st.columns(2)

    if save_col.button("Save", type="primary", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            doc = yaml.safe_load(current_yaml) or {}
        except yaml.YAMLError:
            st.error("Could not parse the contract YAML.")
            return

        patched = False
        for tbl in (doc.get("schema") or []):
            if tbl.get("name") == table_name:
                for prop in (tbl.get("properties") or []):
                    if prop.get("name") == col_name:
                        if claim_name == "Classification":
                            if new_value:
                                prop["classification"] = new_value
                            else:
                                prop.pop("classification", None)
                        elif claim_name == "Description":
                            if new_value:
                                prop["description"] = new_value
                            else:
                                prop.pop("description", None)
                        elif claim_name == "CDE":
                            if new_cde:
                                prop["criticalDataElement"] = True
                            else:
                                prop.pop("criticalDataElement", None)
                        patched = True
                        break
            if patched:
                break

        if not patched:
            st.warning(f"Could not locate `{table_name}.{col_name}` in the contract — no changes made.")
            return

        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        with st.spinner("Saving…"):
            result: ContractDiff = run_import_data_contract(patched_yaml, table_group_id, dry_run=False)

        if result.errors:
            for err in result.errors:
                st.error(err)
        else:
            st.success("Saved.")
            st.session_state.pop(yaml_key, None)
            safe_rerun()

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()

    st.divider()
    if st.button("Delete Claim", key="claim_edit_delete", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            doc = yaml.safe_load(current_yaml) or {}
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
        _persist_governance_deletion(claim_name, table_group_id, table_name, col_name)
        # Store patched YAML — do NOT pop and re-export, which would restore the claim
        st.session_state[yaml_key] = patched_yaml
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

    st.divider()
    save_col, cancel_col = st.columns(2)

    if save_col.button("Save", type="primary", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            doc = yaml.safe_load(current_yaml) or {}
        except yaml.YAMLError:
            st.error("Could not parse current contract YAML.")
            return

        quality = doc.get("quality") or []
        patched = False
        for q in quality:
            if str(q.get("id", "")) == rule_id:
                if op_key and new_threshold:
                    try:
                        q[op_key] = float(new_threshold) if "." in str(new_threshold) else int(new_threshold)
                    except ValueError:
                        q[op_key] = new_threshold
                if has_between and new_lo is not None and new_hi is not None:
                    try:
                        q["mustBeBetween"] = [
                            float(new_lo) if "." in new_lo else int(new_lo),
                            float(new_hi) if "." in new_hi else int(new_hi),
                        ]
                    except ValueError:
                        pass
                if new_desc and new_desc != (rule.get("name") or ""):
                    q["name"] = new_desc
                if new_severity != current_sev:
                    if new_severity is None:
                        q.pop("severity", None)
                    else:
                        q["severity"] = new_severity
                patched = True
                break

        if not patched:
            st.warning(f"Rule `{rule_id[:8]}…` not found in contract YAML — no changes made.")
            return

        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        with st.spinner("Saving…"):
            result: ContractDiff = run_import_data_contract(patched_yaml, table_group_id, dry_run=False)

        if result.errors:
            for err in result.errors:
                st.error(err)
        else:
            st.success(f"Saved {result.total_changes} change(s).")
            st.session_state.pop(yaml_key, None)
            safe_rerun()

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Overview tab orchestrator
# ---------------------------------------------------------------------------

def _render_overview(
    doc: dict,
    anomalies: list[dict],
    table_group_id: str,
    yaml_key: str,
) -> None:
    schema = doc.get("schema") or []
    quality = doc.get("quality") or []
    references = doc.get("references") or []
    sla = doc.get("slaProperties") or []
    team = doc.get("team") or {}
    compliance = doc.get("compliance") or {}

    filter_key = f"dc_filter:{table_group_id}"
    active_filter: str | None = st.session_state.get(filter_key)

    # 1 — Health dashboard
    _render_health_dashboard(doc, anomalies, table_group_id)

    if not schema:
        st.info("No schema data available. Run profiling to populate the contract.")
        return

    # 3 — Gap analysis
    with st.expander("⚠️ **Completeness Analysis**", expanded=False):
        _render_gap_analysis(schema, quality, references, anomalies)

    # 2 — Coverage matrix
    st.markdown("#### Coverage Matrix")
    _render_coverage_matrix(schema, quality, references, anomalies, active_filter)

    # 4 + 5 — Claims detail (static/live split, border-stripe cards)
    st.markdown("#### Claims Detail")
    _render_contract_legend()
    _render_schema_claims(schema, quality, references, anomalies, table_group_id, yaml_key, active_filter)

    if sla or team or compliance:
        _render_sla_team_compliance(sla, team, compliance)


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

    # ── Coverage matrix rows ──────────────────────────────────────────────────
    rules_by_element_full, anomalies_by_col, refs_by_col = _build_lookups(quality, references, anomalies)
    matrix_rows: list[dict] = []
    for table in schema:
        table_name = table.get("name", "")
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
            matrix_rows.append({
                "table":              table_name,
                "column":             col_name,
                "type":               prop.get("physicalType") or "",
                "not_null":           "Req" if (prop.get("required") or prop.get("nullable") is False) else "",
                "key":                "🔑 PK" if opts.get("primaryKey") else ("🔗 FK" if col_refs else ""),
                "tests_status":       worst_test,
                "tests_count":        len(col_rules),
                "anomaly_likelihood": worst_anomaly,
                "anomaly_count":      len(col_anomalies),
                "classification":     prop.get("classification") or "",
                "cde":                bool(prop.get("criticalDataElement")),
                "tiers":              _column_coverage_tiers(prop, quality),
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
            gap_items.append({"table": table_name, "msg": f"Table has no quality tests of any kind", "severity": "warning"})
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
                "name":      "Test",
                "value":     r.get("name") or r.get("testType") or "Test",
                "source":    "test",
                "verif":     "tested",
                "status":    (r.get("lastResult") or {}).get("status") or "not run",
                "rule_id":   str(r.get("id", "") or ""),
                "test_name": r.get("name") or r.get("testType") or "Test",
                "element":   r.get("element") or table_name,
                "dimension": r.get("dimension") or "",
                "severity":  r.get("severity") or "",
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
            claims = _extract_column_claims(prop, col_rules, col_anomalies, col_refs)
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
            cols_data.append({
                "name":          col_name,
                "type":          prop.get("physicalType") or "",
                "is_pk":         bool((prop.get("logicalTypeOptions") or {}).get("primaryKey")),
                "is_fk":         bool(col_refs_full),
                "covered":       is_covered,
                "status":        worst_live,
                "static_claims": [
                    {"name": c["name"], "value": c["value"], "source": c["source"], "verif": c["verif"]}
                    for c in static_claims
                ],
                "live_claims": [
                    {
                        "name":      c["name"],
                        "value":     c["value"],
                        "source":    c["source"],
                        "verif":     c["verif"],
                        "status":    c.get("status") or "",
                        "rule_id":   str(c.get("rule", {}).get("id", "") or ""),
                        "test_name": (c.get("rule", {}).get("name") or c.get("rule", {}).get("testType") or ""),
                        "element":   (c.get("rule", {}).get("element") or ""),
                        "dimension": (c.get("rule", {}).get("dimension") or ""),
                        "severity":  (c.get("rule", {}).get("severity") or ""),
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
# Page
# ---------------------------------------------------------------------------

class DataContractPage(Page):
    path = "data-contract"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "table_group_id" in st.query_params,
    ]
    menu_item = None

    def render(self, table_group_id: str, **_kwargs) -> None:  # noqa: PLR0912
        from testgen.ui.components.widgets.testgen_component import testgen_component  # local import avoids circularity

        table_group = TableGroup.get_minimal(table_group_id)
        if not table_group:
            st.error("Table group not found.")
            return

        testgen.page_header(PAGE_TITLE, "connect-your-database/manage-table-groups/")

        yaml_key    = f"dc_yaml:{table_group_id}"
        anomaly_key = f"dc_anomalies:{table_group_id}"

        if yaml_key not in st.session_state:
            buf = io.StringIO()
            _capture_yaml(table_group_id, buf)
            st.session_state[yaml_key] = buf.getvalue()

        contract_yaml: str = st.session_state[yaml_key]

        doc: dict = {}
        if contract_yaml:
            try:
                doc = yaml.safe_load(contract_yaml) or {}
            except yaml.YAMLError:
                doc = {}

        if anomaly_key not in st.session_state:
            st.session_state[anomaly_key] = _fetch_anomalies(table_group_id)
        anomalies: list[dict] = st.session_state[anomaly_key]

        run_dates    = _fetch_last_run_dates(table_group_id)
        suite_scope  = _fetch_suite_scope(table_group_id)
        test_statuses = _fetch_test_statuses(table_group_id)
        props = _build_contract_props(table_group, doc, anomalies, contract_yaml, run_dates, suite_scope, test_statuses)

        # ── Show import result banner if present ──────────────────────────────
        import_result_key = f"dc_import_result:{table_group_id}"
        if import_result_key in st.session_state:
            result = st.session_state.pop(import_result_key)
            if result.get("errors"):
                for err in result["errors"]:
                    st.error(err)
            elif result.get("changes", 0) == 0:
                st.info("No changes detected — the uploaded contract matches the current state.")
            else:
                st.success(f"Import successful: {result['changes']} change(s) applied.")

        # ── Event handlers ────────────────────────────────────────────────────
        def on_refresh(_payload: object) -> None:
            st.session_state.pop(yaml_key, None)
            st.session_state.pop(anomaly_key, None)
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
            if source == "test":
                _test_claim_dialog(claim, table_name, col_name)
            elif source == "governance" and verif == "declared":
                _claim_edit_dialog(claim, table_name, col_name, table_group_id, yaml_key)
            else:
                _claim_read_dialog(claim, table_name, col_name, table_group_id, yaml_key)

        def on_edit_rule(payload: dict) -> None:
            rule_id = str(payload.get("rule_id", ""))
            rule = next(
                (r for r in (doc.get("quality") or []) if str(r.get("id", "")) == rule_id),
                None,
            )
            if rule:
                _edit_rule_dialog(rule, table_group_id, yaml_key)

        def on_import_contract(yaml_str: str) -> None:
            try:
                result: ContractDiff = run_import_data_contract(yaml_str, table_group_id, dry_run=False)
                st.session_state[import_result_key] = {
                    "errors":  result.errors,
                    "changes": result.total_changes,
                }
                st.session_state.pop(yaml_key, None)
                st.session_state.pop(anomaly_key, None)
            except Exception as exc:  # noqa: BLE001
                st.session_state[import_result_key] = {"errors": [str(exc)], "changes": 0}
            safe_rerun()

        testgen_component(
            "data_contract",
            props=props,
            event_handlers={
                "RefreshClicked":        on_refresh,
                "EditRuleClicked":       on_edit_rule,
                "ImportContractClicked": on_import_contract,
                "ClaimDetailClicked":    on_claim_detail,
                "SuitePickerClicked":    on_suite_picker,
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
        return {"included": [], "excluded": [], "total": 0}


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
                                          AND tr.disposition != 'Inactive'
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


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

def _render_meta_bar(table_group: object, doc: dict) -> None:
    status = doc.get("status", "draft")
    color = _STATUS_COLOR.get(status, "gray")
    version = doc.get("version") or "—"
    domain = doc.get("domain") or ""
    data_product = doc.get("dataProduct") or ""
    servers = doc.get("servers") or []
    server_type = servers[0].get("type", "") if servers else ""

    pills = [f"v{version}", f":{color}[{status.capitalize()}]"]
    if domain:
        pills.append(f"Domain: {domain}")
    if data_product:
        pills.append(f"Product: {data_product}")
    if server_type:
        pills.append(f"Server: {server_type}")

    tg_name = getattr(table_group, "table_groups_name", "")
    st.markdown(f"**{tg_name}** &nbsp;·&nbsp; " + " &nbsp;·&nbsp; ".join(pills))

    if isinstance(doc.get("description"), dict) and doc["description"].get("purpose"):
        st.caption(doc["description"]["purpose"])


# ---------------------------------------------------------------------------
# SLA / Team / Compliance section
# ---------------------------------------------------------------------------

def _render_sla_team_compliance(sla: list[dict], team: dict, compliance: dict) -> None:
    parts = []
    if sla:
        parts.append(f"{len(sla)} SLA propert(ies)")
    if team:
        parts.append(f"Team: {team.get('name', '')}")
    if compliance:
        overall = compliance.get("overall", "unknown")
        parts.append(f"Overall: {_STATUS_ICON.get(overall, '')} {overall.capitalize()}")

    with st.expander(f"ℹ️ **SLA · Team · Compliance** &nbsp;&nbsp;&nbsp; {' · '.join(parts)}", expanded=False):  # noqa: RUF001
        if sla:
            st.markdown("**SLA Properties**")
            for item in sla:
                st.markdown(
                    f"- **{item.get('property', '')}**: {item.get('value', '')} "
                    f"{item.get('unit', '')} — {item.get('description', '')}"
                )

        if team:
            st.markdown(f"**Team:** {team.get('name', '')}")

        if compliance:
            overall = compliance.get("overall", "unknown")
            st.markdown(f"**Overall Compliance:** {_STATUS_ICON.get(overall, '')} {overall.capitalize()}")
            by_dim = compliance.get("byDimension") or {}
            if by_dim:
                cols = st.columns(min(len(by_dim), 6))
                for col, (dim, s) in zip(cols, by_dim.items(), strict=False):
                    col.metric(dim.capitalize(), f"{_STATUS_ICON.get(s, '')} {s.capitalize()}")
            for v in compliance.get("violatedTests") or []:
                st.warning(
                    f"{v.get('name', '')} — {v.get('element', '')} — {v.get('status', '')} — {v.get('message', '')}",
                    icon=":material/warning:",
                )


# ---------------------------------------------------------------------------
# Table builders (used in detail dialogs)
# ---------------------------------------------------------------------------

def _props_to_rows(props: list[dict], quality: list[dict] | None = None) -> list[dict]:
    all_rules = quality or []
    rows = []
    for p in props:
        opts = p.get("logicalTypeOptions") or {}
        tiers = _column_coverage_tiers(p, all_rules)
        rows.append({
            "Column": p.get("name", ""),
            "Enforcement": _tier_badge(tiers),
            "Description": p.get("description") or "",
            "Physical Type": p.get("physicalType", ""),
            "Logical Type": p.get("logicalType", ""),
            "Required": "✓" if p.get("required") else "",
            "CDE": "★" if p.get("criticalDataElement") else "",
            "Classification": p.get("classification", ""),
            "Min Len": opts["minLength"] if opts.get("minLength") is not None else "",
            "Max Len": opts["maxLength"] if opts.get("maxLength") is not None else "",
            "Format": opts.get("format", ""),
            "Examples": ", ".join(p.get("examples") or []),
        })
    return rows


def _rules_to_rows(rules: list[dict], show_origin: bool = False) -> list[dict]:
    rows = []
    for r in rules:
        last = r.get("lastResult") or {}
        status = last.get("status") or "not run"
        icon = _STATUS_ICON.get(status, "")
        row: dict = {
            "Status": f"{icon} {status}",
            "Name": r.get("name") or r.get("testType") or r.get("type", ""),
            "Element": r.get("element", ""),
            "Dimension": r.get("dimension", ""),
            "Type": r.get("type", ""),
            "Severity": r.get("severity", ""),
        }
        if show_origin:
            origin = r.get("origin", "")
            row["Origin"] = "✎ business rule" if origin == "business_rule" else "⚙ auto-generated"
        if last.get("measuredValue") is not None:
            row["Measured"] = str(last["measuredValue"])
        if last.get("message"):
            row["Message"] = str(last["message"])[:80]
        rows.append(row)
    return rows


def _anomaly_rows(anomalies: list[dict]) -> list[dict]:
    return [
        {
            "Likelihood": a.get("issue_likelihood", ""),
            "Table": a.get("table_name", ""),
            "Column": a.get("column_name", ""),
            "Anomaly": a.get("anomaly_name", ""),
            "Description": (a.get("anomaly_description") or "")[:120],
            "Detail": (a.get("detail") or "")[:100],
            "Suggested Action": (a.get("suggested_action") or "")[:100],
        }
        for a in anomalies
    ]


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
# Upload tab
# ---------------------------------------------------------------------------

def _render_upload_section(table_group_id: str, yaml_key: str) -> None:
    st.markdown(
        "Upload a modified YAML to sync selected fields back to TestGen. "
        "Only the fields listed below are writable — everything else is ignored.\n\n"
        "**Updated on upload:** contract version, status, description, business domain, data product, "
        "latency SLA (profiling delay days), and quality rule thresholds, tolerances, severity, and description.\n\n"
        "**Not updated (manage in TestGen directly):** tables, columns, data types, "
        "which quality rules exist, test suite settings, and connections."
    )

    uploaded = st.file_uploader(
        "Choose a YAML file",
        type=["yaml", "yml"],
        key=f"contract_upload:{table_group_id}",
        help="Must be a valid ODCS v3.1.0 data contract document.",
    )

    if uploaded is None:
        return

    yaml_content = uploaded.read().decode("utf-8")

    diff_key = f"dc_diff:{table_group_id}"
    uploaded_yaml_key = f"dc_uploaded_yaml:{table_group_id}"

    if st.session_state.get(uploaded_yaml_key) != yaml_content:
        with st.spinner("Validating contract…"):
            diff: ContractDiff = run_import_data_contract(yaml_content, table_group_id, dry_run=True)
        st.session_state[diff_key] = diff
        st.session_state[uploaded_yaml_key] = yaml_content

    diff = st.session_state.get(diff_key)
    if diff is None:
        return

    if diff.errors:
        for err in diff.errors:
            st.error(err, icon=":material/error:")
        return

    for warn in diff.warnings:
        st.warning(warn, icon=":material/warning:")

    if diff.total_changes == 0:
        st.info("No changes detected — the uploaded contract matches the current state.", icon=":material/check_circle:")
        return

    st.markdown(f"**Preview of changes ({diff.summary()}):**")

    if diff.contract_updates:
        st.markdown("*Contract fields:*")
        for col, val in diff.contract_updates.items():
            st.markdown(f"  - `{col}` → `{val}`")

    if diff.table_group_updates:
        st.markdown("*Table Group fields:*")
        for col, val in diff.table_group_updates.items():
            st.markdown(f"  - `{col}` → `{val}`")

    if diff.test_updates:
        st.markdown(f"*{len(diff.test_updates)} quality rule update(s):*")
        for upd in diff.test_updates[:10]:
            test_id = upd.get("id", "")
            changes = {k: v for k, v in upd.items() if k != "id"}
            st.markdown(f"  - Test `{test_id[:8]}…`: {changes}")
        if len(diff.test_updates) > 10:
            st.caption(f"  … and {len(diff.test_updates) - 10} more.")

    if st.button(
        f":material/upload: Apply {diff.total_changes} Change(s)",
        type="primary",
        key=f"apply_contract:{table_group_id}",
    ):
        with st.spinner("Applying changes…"):
            result: ContractDiff = run_import_data_contract(yaml_content, table_group_id, dry_run=False)
        if result.errors:
            for err in result.errors:
                st.error(err)
        else:
            st.success(f"Applied {result.total_changes} change(s) successfully.")
            for k in (yaml_key, diff_key, uploaded_yaml_key):
                st.session_state.pop(k, None)
            safe_rerun()
