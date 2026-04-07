"""
Data Contract — all @st.dialog functions and supporting UI render helpers.

These functions depend on Streamlit and must only be called from within a
running Streamlit app.  Pure logic (YAML mutation, pending edits) lives in
data_contract_yaml.py; DB access lives in data_contract_queries.py.
"""
from __future__ import annotations

import html
import logging

import streamlit as st
import yaml

from testgen.commands.contract_staleness import StaleDiff
from testgen.commands.contract_versions import save_contract_version
from testgen.ui.navigation.router import Router
from testgen.ui.queries.data_contract_queries import (
    _capture_yaml,
    _dismiss_hygiene_anomaly,
    _fetch_governance_data,
    _fetch_test_live_info,
    _lookup_column_id,
    _persist_governance_deletion,
    _persist_pending_edits,
    _save_governance_data,
)
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session
from testgen.ui.views.data_contract_props import _STATUS_ICON, _VERIF_META
from testgen.ui.views.data_contract_yaml import (
    _apply_pending_governance_edit,
    _apply_pending_test_edit,
    _delete_term_yaml_patch,
    _patch_yaml_governance,
)

LOG = logging.getLogger("testgen")

# ---------------------------------------------------------------------------
# Dialog-local constants
# ---------------------------------------------------------------------------

_VERIF_LABEL: dict[str, str] = {k: f"{v[0]} {v[1]}" for k, v in _VERIF_META.items()}

_SRC_LABEL: dict[str, str] = {
    "ddl": "DDL", "profiling": "Profiling", "governance": "Governance", "test": "Test",
}

_SRC_NOTE: dict[str, str] = {
    "ddl":       "Column type, constraints, and keys come from the physical database schema. "
                 "These values are enforced by the database and cannot be changed here.",
    "profiling": "This value was measured from actual data during a profiling run. "
                 "It is a snapshot of what TestGen observed, not an active constraint.",
}

# Terms that can be removed from the YAML for each source type.
_DELETABLE_TERMS: dict[str, set[str]] = {
    "governance": {"Classification", "CDE", "Description"},
    "profiling":  {"Min Value", "Max Value", "Min Length", "Max Length", "Format", "Logical Type"},
    "ddl":        {"Not Null", "Primary Key", "Foreign Key", "Data Type"},
}

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


# ---------------------------------------------------------------------------
# Shared modal header
# ---------------------------------------------------------------------------

def _modal_header(verif: str, name: str, table_name: str, col_name: str, subtitle: str = "") -> None:
    """Render a consistent modal header for all term/governance dialogs.

    Line 1 (bold 17px): {icon} {verif_label} — {name}
    Line 2 (caption monospace): table_name · col_name
    Optional subtitle below divider.
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


# ---------------------------------------------------------------------------
# Live-terms row (Streamlit render, calls dialog functions)
# ---------------------------------------------------------------------------

def _render_live_terms_row(
    col_key: str,
    live_terms: list[dict],
    table_group_id: str,
    yaml_key: str,
) -> None:
    """Render live (test + anomaly) terms as Streamlit bordered containers with optional edit."""
    if not live_terms:
        return

    n    = len(live_terms)
    cols = st.columns(min(n, 4))
    for i, term in enumerate(live_terms):
        with cols[i % 4]:
            term_name  = term.get("name", "Test")
            is_test    = term_name == "Test"
            is_monitor = term_name == "Monitor"
            status     = term.get("status", "not run")
            if term_name == "Hygiene":
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
                f'margin:2px 0 0 0;">{html.escape(str(term["value"]))}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if (is_test or is_monitor) and term.get("rule"):
                rule    = term["rule"]
                rule_id = str(rule.get("id", ""))
                if rule_id:
                    btn_key   = f"edit_{col_key}_{rule_id[:8]}_{i}"
                    btn_label = "📡 Detail" if is_monitor else "✏️ Edit"
                    if st.button(btn_label, key=btn_key, type="tertiary", use_container_width=True):
                        if is_monitor:
                            _monitor_term_dialog(rule, term_name)
                        else:
                            _edit_rule_dialog(rule, table_group_id, yaml_key)


# ---------------------------------------------------------------------------
# Governance edit dialog
# ---------------------------------------------------------------------------

@st.dialog("Governance Metadata", width="large")
def _governance_edit_dialog(
    column_id: str,
    table_name: str,
    col_name: str,
    table_group_id: str,
    yaml_key: str,
) -> None:
    """Edit all governance metadata for a column, writing directly to data_column_chars."""
    gov_map = _fetch_governance_data(table_group_id)
    gov     = gov_map.get((table_name, col_name)) or {}

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

    if can_edit_pii:
        current_pii = gov.get("pii_flag")
        is_pii      = st.checkbox("Contains PII", value=bool(current_pii))
        updates["pii_flag"] = "MANUAL" if is_pii else None
    else:
        st.caption("🔒 PII classification: requires view_pii permission to edit.")

    st.divider()

    updates["description"] = st.text_area(
        "Description",
        value=gov.get("description") or "",
        height=80,
        placeholder="Describe what this column contains…",
    )

    st.divider()

    tag_labels = {
        "data_source":       "Data Source",
        "source_system":     "Source System",
        "source_process":    "Source Process",
        "business_domain":   "Business Domain",
        "stakeholder_group": "Stakeholder Group",
        "transform_level":   "Transform Level",
        "aggregation_level": "Aggregation Level",
        "data_product":      "Data Product",
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
        try:
            _save_governance_data(effective_column_id, updates)
        except Exception:
            LOG.exception("_governance_edit_dialog: failed to save governance data")
            st.error("Failed to save — check logs for details.")
            return
        st.session_state.pop(yaml_key, None)
        safe_rerun()
    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Suite picker dialog
# ---------------------------------------------------------------------------

@st.dialog("Select Test Suite", width="small")
def _suite_picker_dialog(suite_runs: list[dict], project_code: str = "", table_group_id: str = "") -> None:
    """Let the user choose which suite's results to drill into."""
    st.caption("This contract covers multiple test suites.")
    for sr in suite_runs:
        total    = sr.get("test_ct", 0)
        passed   = sr.get("passed_ct", 0)
        failed   = sr.get("failed_ct", 0) + sr.get("error_ct", 0)
        warn     = sr.get("warning_ct", 0)
        date     = sr.get("run_start", "")
        name     = sr.get("suite_name", "")
        run_id   = sr.get("run_id", "")
        suite_id = sr.get("suite_id", "")

        border_color  = "#c62828" if failed else "#f9a825" if warn else "#2e7d32"
        status_parts: list[str] = []
        if passed: status_parts.append(f"✅ {passed} passed")
        if warn:   status_parts.append(f"⚠️ {warn} warnings")
        if failed: status_parts.append(f"❌ {failed} failed")
        sub = "  ·  ".join(status_parts) if status_parts else f"{total} tests"
        if date:
            sub += f"  ·  {date}"

        c_info, c_results, c_suite = st.columns([3, 1, 1])
        with c_info:
            st.markdown(
                f'<div style="border-left:3px solid {border_color};padding:5px 10px;margin:4px 0;">'
                f'<div style="font-size:13px;font-weight:600;">{html.escape(name)}</div>'
                f'<div style="font-size:11px;color:#888;">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        if run_id and c_results.button("Results →", key=f"suite_pick_run_{run_id}"):
            Router().queue_navigation(to="test-runs:results", with_args={"run_id": run_id})
            safe_rerun()
        if suite_id and project_code and c_suite.button("Suite →", key=f"suite_pick_def_{suite_id}"):
            Router().queue_navigation(
                to="test-suites:definitions",
                with_args={
                    "project_code":    project_code,
                    "table_group_id":  table_group_id,
                    "test_suite_name": name,
                },
            )
            safe_rerun()

    st.divider()
    if st.button("Cancel", key="suite_pick_cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Monitor term dialog (read-only)
# ---------------------------------------------------------------------------

@st.dialog("Monitor Term Detail", width="small")
def _monitor_term_dialog(rule: dict, term_name: str, table_name: str = "", col_name: str = "") -> None:  # noqa: ARG001
    test_type   = rule.get("testType", "")
    icon        = _MONITOR_ICON.get(test_type, "📡")  # noqa: F841
    description = _MONITOR_DESCRIPTION.get(
        test_type, "A continuous monitor watches this element for anomalies over time."
    )
    monitor_name = rule.get("name") or test_type or "Monitor"
    last         = rule.get("lastResult") or {}
    status       = last.get("status") or "not run"
    status_icon  = _STATUS_ICON.get(status, "⏳")

    _modal_header("monitored", monitor_name, table_name, col_name, subtitle=description)
    st.divider()
    st.markdown(f"**Status** &nbsp; {status_icon} {status.title() if status else 'Not Run'}")
    if last.get("measuredValue") is not None:
        st.markdown(f"**Last Measured** &nbsp; `{last['measuredValue']}`")
    if last.get("executedAt"):
        st.markdown(f"**Last Run** &nbsp; {last['executedAt']}")
    st.divider()
    st.caption("📡 Managed in TestGen Monitors. To configure or run it, go to Monitors.")
    st.caption("To delete the term from the contract go to the monitors page.")
    if st.button("Close", key="monitor_term_close", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Test term dialog (read-only detail + navigate to suite)
# ---------------------------------------------------------------------------

@st.dialog("Test Term Detail", width="small")
def _test_term_dialog(
    term: dict,
    table_name: str,
    col_name: str,
    project_code: str,
    yaml_key: str = "",
    table_group_id: str = "",
) -> None:
    status      = term.get("status", "")
    status_icon = _STATUS_ICON.get(status, "⏳")  # noqa: F841
    test_name   = term.get("test_name") or "Test"
    dimension   = term.get("dimension", "")
    severity    = term.get("severity", "")
    rule_id     = term.get("rule_id", "")

    live_info   = _fetch_test_live_info(rule_id) if rule_id else {}
    suite_id    = live_info.get("suite_id", "")
    live_status = live_info.get("status", "") or status
    live_status_icon = _STATUS_ICON.get(live_status, "⏳")
    test_time   = live_info.get("test_time")

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
    status_label     = live_status.title() if live_status else "Not Run"

    _modal_header("tested", test_name_short, table_name, col_name, subtitle=type_description)
    if user_description:
        st.caption(f"Notes: {user_description}")

    meta: list[tuple[str, str]] = [
        ("Status",   f"{live_status_icon} {status_label}"),
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
        if btn_col.button("Edit test", key="test_term_goto", use_container_width=True):
            Router().queue_navigation(
                to="test-suites:definitions",
                with_args={"test_suite_id": suite_id, "project_code": project_code},
            )
            safe_rerun()
    if close_col.button("Close", key="test_term_close", use_container_width=True):
        safe_rerun()

    if yaml_key and table_group_id and rule_id:
        st.divider()
        if st.button("Delete term from contract", key="test_term_delete", use_container_width=True):
            current_yaml = st.session_state.get(yaml_key, "")
            try:
                _parsed = yaml.safe_load(current_yaml)
                if not isinstance(_parsed, dict):
                    st.error("Could not parse the contract YAML — unexpected format.")
                    return
                doc = _parsed
            except yaml.YAMLError:
                st.error("Could not parse current contract YAML.")
                return
            quality = doc.get("quality") or []
            before = len(quality)
            doc["quality"] = [q for q in quality if str(q.get("id", "")) != rule_id]
            if len(doc["quality"]) == before:
                st.warning(f"Rule `{rule_id[:8]}…` not found in contract YAML — no changes made.")
                return
            patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
            st.session_state[yaml_key] = patched_yaml
            pending_key = f"dc_pending:{table_group_id}"
            st.session_state[pending_key] = _apply_pending_test_edit(
                st.session_state.get(pending_key, {}),
                rule_id,
                {
                    "_removed": True,
                    "_table": table_name,
                    "_col": col_name,
                    "_snapshot": {"name": test_name_short, "source": "test", "verif": "tested"},
                },
            )
            safe_rerun()


# ---------------------------------------------------------------------------
# Term read-only dialog
# ---------------------------------------------------------------------------

@st.dialog("Term Detail", width="small")
def _term_read_dialog(
    term: dict,
    table_name: str,
    col_name: str,
    table_group_id: str,
    yaml_key: str,
) -> None:
    src        = term.get("source", "")
    verif      = term.get("verif", "")
    term_name  = term.get("name", "")
    can_delete = term_name in _DELETABLE_TERMS.get(src, set())

    _modal_header(verif, term_name, table_name, col_name)
    st.divider()
    st.write(term.get("full_value") or term.get("value", ""))
    note = _SRC_NOTE.get(src, "")
    if note:
        st.caption(f"ℹ️ {note}")
    if src == "ddl" and can_delete:
        st.caption("⚠️ Schema-derived terms will reappear when you generate a new contract version.")
    if src in ("profiling", "ddl") and can_delete:
        st.caption("⚠️ This change is temporary and will be lost when you generate a new contract version.")

    st.divider()
    if term_name == "Hygiene":
        anomaly_type = term.get("anomaly_type", "")
        st.caption("🔍 Hygiene findings are live data quality anomalies detected during profiling.")
        dis_col, close_col = st.columns(2)
        if dis_col.button("Delete term from contract", key="hygiene_dismiss", use_container_width=True):
            if anomaly_type:
                _dismiss_hygiene_anomaly(table_group_id, table_name, col_name, anomaly_type)
            # Clear the cached anomaly list so the dismissed chip disappears on next render
            st.session_state.pop(f"dc_anomalies:{table_group_id}", None)
            pending_key = f"dc_pending:{table_group_id}"
            st.session_state[pending_key] = _apply_pending_governance_edit(
                st.session_state.get(pending_key, {}),
                table_name, col_name, f"Hygiene:{anomaly_type or term.get('value', '')}",
                None,
                snapshot={"name": "Hygiene", "source": "profiling", "verif": "observed"},
            )
            safe_rerun()
        if close_col.button("Close", key="hygiene_close", use_container_width=True):
            safe_rerun()
        return
    if can_delete:
        del_col, close_col = st.columns(2)
        if del_col.button("Delete term from contract", key="term_read_delete", use_container_width=True):
            current_yaml = st.session_state.get(yaml_key, "")
            try:
                _parsed = yaml.safe_load(current_yaml)
                if not isinstance(_parsed, dict):
                    st.error("Could not parse the contract YAML — unexpected format.")
                    return
                doc = _parsed
            except yaml.YAMLError:
                st.error("Could not parse the contract YAML.")
                return
            patched, err = _delete_term_yaml_patch(
                term_name, src, table_name, col_name, term.get("value", ""), doc
            )
            if not patched:
                st.error(err or "Could not remove this term.")
                return
            patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
            pending_key = f"dc_pending:{table_group_id}"
            if src == "governance":
                _persist_governance_deletion(term_name, table_group_id, table_name, col_name)
            else:
                # Track profiling/DDL deletions in pending so the banner shows,
                # pending_count changes (triggering VanJS re-render), and cancel can restore them.
                # Store a snapshot so the JS can render a grayed-out "deleted" card.
                st.session_state[pending_key] = _apply_pending_governance_edit(
                    st.session_state.get(pending_key, {}),
                    table_name, col_name, term_name, None,
                    snapshot={"name": term_name, "source": src, "verif": verif},
                )
            st.session_state[yaml_key] = patched_yaml
            safe_rerun()
        if close_col.button("Close", key="term_read_close", use_container_width=True):
            safe_rerun()
    else:
        if st.button("Close", key="term_read_close", use_container_width=True):
            safe_rerun()


# ---------------------------------------------------------------------------
# Term edit dialog (governance)
# ---------------------------------------------------------------------------

@st.dialog("Edit Governance Term", width="small")
def _term_edit_dialog(
    term: dict,
    table_name: str,
    col_name: str,
    table_group_id: str,
    yaml_key: str,
) -> None:
    term_name     = term.get("name", "")
    current_value = term.get("full_value") or term.get("value", "")

    _modal_header("declared", term_name, table_name, col_name)

    if term_name == "CDE":
        new_cde: bool   = st.checkbox("Mark as Critical Data Element", value=True)
        new_value: str  = "true" if new_cde else ""
    elif term_name == "Description":
        new_value = st.text_area("Description", value=current_value, height=120)
    else:
        new_value = st.text_input(term_name, value=current_value)

    st.divider()
    save_col, cancel_col = st.columns(2)
    st.caption("ℹ Changes are held until you save a new contract version.")

    if save_col.button("Save", type="primary", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            _parsed = yaml.safe_load(current_yaml)
            if not isinstance(_parsed, dict):
                st.error("Could not parse the contract YAML — unexpected format.")
                return
            doc = _parsed
        except yaml.YAMLError:
            st.error("Could not parse the contract YAML.")
            return

        edit_value: object = new_value
        if term_name == "CDE":
            edit_value = new_cde

        patched = _patch_yaml_governance(doc, table_name, col_name, term_name, edit_value)
        if not patched:
            st.warning(f"Could not locate `{table_name}.{col_name}` in the contract — no changes made.")
            return

        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        st.session_state[yaml_key] = patched_yaml
        pending_key = f"dc_pending:{table_group_id}"
        LOG.debug("Pending governance edit: %s.%s %s = %r", table_name, col_name, term_name, edit_value)
        st.session_state[pending_key] = _apply_pending_governance_edit(
            st.session_state.get(pending_key, {}),
            table_name, col_name, term_name, edit_value,
        )
        safe_rerun()

    if cancel_col.button("Close", use_container_width=True):
        safe_rerun()

    st.divider()
    if st.button("Delete term from contract", key="term_edit_delete", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            _parsed = yaml.safe_load(current_yaml)
            if not isinstance(_parsed, dict):
                st.error("Could not parse the contract YAML — unexpected format.")
                return
            doc = _parsed
        except yaml.YAMLError:
            st.error("Could not parse the contract YAML.")
            return
        patched, err = _delete_term_yaml_patch(
            term_name, "governance", table_name, col_name, current_value, doc
        )
        if not patched:
            st.error(err or "Could not remove this term.")
            return
        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        st.session_state[yaml_key] = patched_yaml
        _persist_governance_deletion(term_name, table_group_id, table_name, col_name)
        pending_key = f"dc_pending:{table_group_id}"
        st.session_state[pending_key] = _apply_pending_governance_edit(
            st.session_state.get(pending_key, {}),
            table_name, col_name, term_name, None,
            snapshot={"name": term_name, "source": "governance", "verif": term.get("verif", "declared")},
        )
        safe_rerun()


# ---------------------------------------------------------------------------
# Quality rule edit dialog
# ---------------------------------------------------------------------------

@st.dialog("Edit Quality Rule", width="small")
def _edit_rule_dialog(rule: dict, table_group_id: str, yaml_key: str) -> None:
    rule_id   = str(rule.get("id", ""))
    test_name = rule.get("name") or rule.get("type") or "Test"
    last      = rule.get("lastResult") or {}

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
            if not isinstance(_parsed, dict):
                st.error("Could not parse the contract YAML — unexpected format.")
                return
            doc = _parsed
        except yaml.YAMLError:
            st.error("Could not parse current contract YAML.")
            return

        quality     = doc.get("quality") or []
        patched     = False
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

    st.divider()
    if st.button("Delete term from contract", key="rule_delete_btn", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            _parsed = yaml.safe_load(current_yaml)
            if not isinstance(_parsed, dict):
                st.error("Could not parse the contract YAML — unexpected format.")
                return
            doc = _parsed
        except yaml.YAMLError:
            st.error("Could not parse current contract YAML.")
            return

        quality = doc.get("quality") or []
        before  = len(quality)
        doc["quality"] = [q for q in quality if str(q.get("id", "")) != rule_id]
        if len(doc["quality"]) == before:
            st.warning(f"Rule `{rule_id[:8]}…` not found in contract YAML — no changes made.")
            return

        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        st.session_state[yaml_key] = patched_yaml
        pending_key = f"dc_pending:{table_group_id}"
        LOG.debug("Pending rule removal: rule_id=%s", rule_id)
        st.session_state[pending_key] = _apply_pending_test_edit(
            st.session_state.get(pending_key, {}),
            rule_id,
            {"_removed": True},
        )
        safe_rerun()


# ---------------------------------------------------------------------------
# Regenerate dialog
# ---------------------------------------------------------------------------

@st.dialog("Regenerate Contract", width="small")
def _regenerate_dialog(table_group_id: str, current_version: int | None, pending_ct: int = 0) -> None:
    """Re-export the contract from the live database and save it as a new version."""
    import io as _io
    next_ver = (current_version + 1) if current_version is not None else 0
    st.markdown(f"**Re-export and save as Version {next_ver}**")
    st.caption(
        "This will re-generate the full contract YAML from the current database state "
        "(test definitions, profiling results, governance metadata) and save it as a new version."
    )
    confirmed = True
    if pending_ct > 0:
        st.warning(
            f"You have **{pending_ct} unsaved edit(s)** that will be discarded. "
            "Save a new version first if you want to keep them.",
            icon="⚠️",
        )
        confirmed = st.checkbox("I understand — discard my pending edits and regenerate")
    label = st.text_input("Label (optional)", placeholder="e.g. Regenerated with test descriptions")
    st.divider()
    go_col, cancel_col = st.columns(2)
    if go_col.button("Regenerate & Save", type="primary", use_container_width=True, disabled=not confirmed):
        with st.spinner("Exporting from database…"):
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
# Save version dialog
# ---------------------------------------------------------------------------

@st.dialog("Save New Version", width="small")
def _save_version_dialog(
    table_group_id: str,
    pending: dict,
    current_yaml: str,
    current_version: int | None,
) -> None:
    gov_edits  = pending.get("governance", [])
    test_edits = pending.get("tests", [])
    next_ver   = (current_version + 1) if current_version is not None else 0

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
        try:
            with st.spinner("Saving…"):
                # 1. Apply all pending edits to DB (governance + tests)
                _persist_pending_edits(table_group_id, pending)

                # 2. Save snapshot from the in-memory patched YAML (not a fresh export)
                new_version = save_contract_version(table_group_id, current_yaml, label or None)

            st.success(f"Saved as version {new_version}.")
            pending_key = f"dc_pending:{table_group_id}"
            yaml_key    = f"dc_yaml:{table_group_id}"
            version_key = f"dc_version:{table_group_id}"
            for k in (pending_key, yaml_key, version_key):
                st.session_state.pop(k, None)
            safe_rerun()

        except Exception as exc:
            st.error(f"Save failed: {exc}")

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Review changes panel
# ---------------------------------------------------------------------------

@st.dialog("Changes Since Last Save", width="large")
def _review_changes_panel(
    stale_diff: StaleDiff,
    table_group_id: str,
    version_record: dict,
    current_yaml: str,
) -> None:
    version_num = version_record.get("version", "?")
    saved_at    = version_record.get("saved_at")
    saved_str   = saved_at.strftime("%b %d, %Y at %H:%M") if saved_at else ""
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
# Cancel all changes dialog
# ---------------------------------------------------------------------------

@st.dialog("Discard Changes", width="small")
def cancel_all_changes_dialog(
    table_group_id: str,
    pending_ct: int,
    original_yaml: str,
) -> None:
    """Confirm and discard all pending (unsaved) edits, restoring the last-saved YAML."""
    noun = "change" if pending_ct == 1 else "changes"
    st.markdown(f"Discard **{pending_ct} unsaved {noun}**? This cannot be undone.")
    st.caption("The contract will be restored to its last saved state.")
    st.divider()
    confirm_col, back_col = st.columns(2)
    if confirm_col.button("Discard", type="primary", use_container_width=True):
        st.session_state.pop(f"dc_pending:{table_group_id}", None)
        st.session_state[f"dc_yaml:{table_group_id}"] = original_yaml
        safe_rerun()
    if back_col.button("Go back", use_container_width=True):
        safe_rerun()
