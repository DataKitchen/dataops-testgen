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

from testgen.commands.contract_snapshot_suite import (
    create_contract_snapshot_suite,
    delete_contract_version,
    sync_import_to_snapshot_suite,
)
from testgen.commands.odcs_contract import ContractDiff, get_updated_yaml, run_import_contract
from testgen.commands.contract_staleness import StaleDiff
from testgen.commands.contract_versions import (
    list_contract_versions,
    rollback_contract_version,
    save_contract_version,
    update_contract_version,
)
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import fetch_dict_from_db
from testgen.common.models import with_database_session
from testgen.common.models.table_group import TableGroup
from testgen.ui.navigation.router import Router
from testgen.ui.queries.data_contract_queries import (
    _capture_yaml,
    _fetch_governance_data,
    _fetch_test_live_info,
    _persist_pending_edits,
)
from testgen.commands.contract_management import create_contract
from testgen.ui.queries.data_contract_list_queries import (
    count_in_scope_tests,
    fetch_eligible_suites_for_wizard,
    fetch_table_groups_for_project,
    fetch_tables_for_wizard,
    is_contract_name_taken,
)
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session
from testgen.ui.views.data_contract_props import _STATUS_ICON, _VERIF_META
from testgen.ui.views.data_contract_yaml import (
    _apply_pending_governance_edit,
    _apply_pending_test_edit,
    _patch_yaml_governance,
)

LOG = logging.getLogger("testgen")

_CONTRACT_CACHE_KEYS = ("dc_pending", "dc_yaml", "dc_version", "dc_run_dates", "dc_gov", "dc_term_diff", "dc_suite_scope", "dc_staleness_diff")


# ─────────────────────────────────────────────────────────────────────────────
# Create Contract Wizard
# ─────────────────────────────────────────────────────────────────────────────

_WIZARD_KEY = "create_contract_wizard"


def _init_wizard_state(
    project_code: str,
    table_group_id: str | None = None,
) -> dict:
    """Initialise (or reset) wizard session state. Returns the state dict."""
    state: dict = {
        "step":              2 if table_group_id else 1,
        "project_code":      project_code,
        "table_group_id":    table_group_id,
        "table_group_name":  None,
        "suite_ids":         None,   # list[str] or None = all
        "table_names":       None,   # list[str] or None = all
        "include_profiling": True,
        "include_ddl":       True,
        "include_hygiene":   True,
        "include_monitors":  True,
        "contract_name":     "",
    }
    st.session_state[_WIZARD_KEY] = state
    return state


def _validate_contract_name(name: str, project_code: str) -> tuple[bool, str]:
    """Return (is_valid, error_message). Empty string error means valid."""
    if not name or not name.strip():
        return False, "Contract name is required."
    if is_contract_name_taken(name.strip(), project_code):
        return False, f"A contract named '{name.strip()}' already exists in this project."
    return True, ""


@st.dialog("Create New Contract", width="large")
def create_contract_wizard(
    project_code: str,
    table_group_id: str | None = None,
) -> None:
    """
    5-step wizard to create a new data contract.

    Step 1 — Table Group (skipped if table_group_id provided)
    Step 2 — Test Suites
    Step 3 — Tables
    Step 4 — Content toggles
    Step 5 — Confirm + Name
    """
    # Initialise or retrieve state
    if _WIZARD_KEY not in st.session_state or st.session_state[_WIZARD_KEY].get("project_code") != project_code:
        state = _init_wizard_state(project_code, table_group_id)
    else:
        state = st.session_state[_WIZARD_KEY]

    step = state["step"]

    # ── Step indicator ─────────────────────────────────────────────
    step_names = ["Table Group", "Suites", "Tables", "Content", "Confirm"]
    total = 5
    st.caption(f"Step {step} of {total} · {step_names[step - 1]}")
    st.divider()

    # ── Step 1: Table Group ─────────────────────────────────────────
    if step == 1:
        st.markdown("**Select a Table Group**")
        tgs = fetch_table_groups_for_project(project_code)
        if not tgs:
            st.warning("No table groups found for this project.")
            return

        options = {tg["id"]: f"{tg['table_groups_name']}  ({tg['contract_count']} contracts)" for tg in tgs}
        selected_id = st.radio(
            "Table group",
            options=list(options.keys()),
            format_func=lambda x: options[x],
            key="wizard_tg_radio",
            label_visibility="collapsed",
        )
        if st.button("Next →", type="primary", disabled=not selected_id):
            tg_name = next(tg["table_groups_name"] for tg in tgs if tg["id"] == selected_id)
            state["table_group_id"] = selected_id
            state["table_group_name"] = tg_name
            state["step"] = 2
            st.session_state[_WIZARD_KEY] = state
            safe_rerun()
        return

    # ── Step 2: Test Suites ────────────────────────────────────────
    if step == 2:
        tg_id = state["table_group_id"]
        if not tg_id:
            st.error("No table group selected. Please go back.")
            if st.button("← Back"):
                state["step"] = 1
                st.session_state[_WIZARD_KEY] = state
                safe_rerun()
            return

        suites = fetch_eligible_suites_for_wizard(tg_id)
        st.markdown("**Select Test Suites to include**")

        if not suites:
            st.warning("No eligible test suites found for this table group.")
            if st.button("← Back"):
                state["step"] = 1
                st.session_state[_WIZARD_KEY] = state
                safe_rerun()
            return

        selected_suite_ids: list[str] = []
        for suite in suites:
            checked = st.checkbox(
                f"{suite['name']}  ({suite['active_test_count']} active tests)",
                value=True,
                key=f"wizard_suite_{suite['id']}",
            )
            if checked:
                selected_suite_ids.append(suite["id"])

        st.caption("Monitor suites are controlled separately in Step 4 → Content.")

        back_col, next_col = st.columns(2)
        if back_col.button("← Back"):
            state["step"] = 1
            st.session_state[_WIZARD_KEY] = state
            safe_rerun()
        if next_col.button("Next →", type="primary", disabled=not selected_suite_ids):
            state["suite_ids"] = selected_suite_ids
            state["step"] = 3
            st.session_state[_WIZARD_KEY] = state
            safe_rerun()
        return

    # ── Step 3: Tables ─────────────────────────────────────────────
    if step == 3:
        tg_id = state["table_group_id"]
        tables = fetch_tables_for_wizard(tg_id)
        st.markdown("**Select Tables to include**")

        if not tables:
            st.warning("No profiled tables found for this table group.")
            if st.button("← Back"):
                state["step"] = 2
                st.session_state[_WIZARD_KEY] = state
                safe_rerun()
            return

        sel_all, sel_none = st.columns(2)
        if sel_all.button("Select all", key="wizard_tbl_all"):
            for t in tables:
                st.session_state[f"wizard_tbl_{t['table_name']}"] = True
        if sel_none.button("None", key="wizard_tbl_none"):
            for t in tables:
                st.session_state[f"wizard_tbl_{t['table_name']}"] = False

        selected_tables: list[str] = []
        for tbl in tables:
            checked = st.checkbox(
                f"{tbl['table_name']}  ({tbl['active_test_count']} tests)",
                value=st.session_state.get(f"wizard_tbl_{tbl['table_name']}", True),
                key=f"wizard_tbl_{tbl['table_name']}",
            )
            if checked:
                selected_tables.append(tbl["table_name"])

        st.caption(f"{len(tables)} tables · {len(selected_tables)} selected")

        back_col, next_col = st.columns(2)
        if back_col.button("← Back"):
            state["step"] = 2
            st.session_state[_WIZARD_KEY] = state
            safe_rerun()
        if next_col.button("Next →", type="primary", disabled=not selected_tables):
            state["table_names"] = selected_tables
            state["step"] = 4
            st.session_state[_WIZARD_KEY] = state
            safe_rerun()
        return

    # ── Step 4: Content ────────────────────────────────────────────
    if step == 4:
        st.markdown("**Select Content to include**")
        state["include_profiling"] = st.toggle("Profiling", value=state.get("include_profiling", True),
                                               help="Schema stats + auto-generated profiling tests")
        state["include_ddl"]       = st.toggle("DDL Constraints", value=state.get("include_ddl", True),
                                               help="Column types, NOT NULL, primary key")
        state["include_hygiene"]   = st.toggle("Hygiene", value=state.get("include_hygiene", True),
                                               help="Data quality anomalies from the latest profiling run")
        state["include_monitors"]  = st.toggle("Monitors", value=state.get("include_monitors", True),
                                               help="Freshness, volume, schema drift, and metric tests")
        st.session_state[_WIZARD_KEY] = state

        back_col, next_col = st.columns(2)
        if back_col.button("← Back"):
            state["step"] = 3
            st.session_state[_WIZARD_KEY] = state
            safe_rerun()
        if next_col.button("Next →", type="primary"):
            state["step"] = 5
            st.session_state[_WIZARD_KEY] = state
            safe_rerun()
        return

    # ── Step 5: Confirm ────────────────────────────────────────────
    if step == 5:
        tg_id         = state["table_group_id"]
        tg_name       = state.get("table_group_name", tg_id)
        suite_ids     = state.get("suite_ids") or []
        table_names   = state.get("table_names") or []
        content_parts = [
            k for k, flag in [
                ("Profiling", state.get("include_profiling", True)),
                ("DDL", state.get("include_ddl", True)),
                ("Hygiene", state.get("include_hygiene", True)),
                ("Monitors", state.get("include_monitors", True)),
            ] if flag
        ]

        st.markdown("**Summary**")
        st.markdown(f"- **Table group:** {tg_name}")
        st.markdown(f"- **Suites:** {len(suite_ids)} selected")
        st.markdown(f"- **Tables:** {len(table_names)} selected")
        st.markdown(f"- **Content:** {' · '.join(content_parts) or 'None'}")

        in_scope = count_in_scope_tests(
            suite_ids, table_names, tg_id, state.get("include_monitors", True)
        )
        st.markdown(f":green[**{in_scope} tests in scope**]")

        contract_name = st.text_input("Contract name (unique within project)", key="wizard_contract_name")
        name_ok, name_err = _validate_contract_name(contract_name, project_code)
        if contract_name and not name_ok:
            st.error(name_err)

        can_create = name_ok and in_scope > 0

        back_col, create_col = st.columns(2)
        if back_col.button("← Back"):
            state["step"] = 4
            st.session_state[_WIZARD_KEY] = state
            safe_rerun()

        if create_col.button(
            "Create Contract", type="primary",
            disabled=not can_create,
            use_container_width=True,
        ):
            result = create_contract(contract_name.strip(), project_code, tg_id)
            new_contract_id = result["contract_id"]

            # Store wizard filter selections for the detail page's first-time flow
            st.session_state[f"dc_wizard_filters:{new_contract_id}"] = {
                "suite_ids":         suite_ids,
                "table_names":       table_names,
                "include_profiling": state.get("include_profiling", True),
                "include_ddl":       state.get("include_ddl", True),
                "include_hygiene":   state.get("include_hygiene", True),
                "include_monitors":  state.get("include_monitors", True),
            }
            # Clear wizard state
            st.session_state.pop(_WIZARD_KEY, None)

            Router().queue_navigation(to="data-contract", with_args={"contract_id": new_contract_id})
            safe_rerun()


def _clear_contract_cache(contract_id: str, *, also_anomalies: bool = False) -> None:
    keys = _CONTRACT_CACHE_KEYS + ("dc_anomalies",) if also_anomalies else _CONTRACT_CACHE_KEYS
    for key in keys:
        st.session_state.pop(f"{key}:{contract_id}", None)


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
    st.caption("ℹ Changes are held until you save a new contract version.")

    if save_col.button("Save", type="primary", use_container_width=True):
        current_yaml = st.session_state.get(yaml_key, "")
        try:
            doc = yaml.safe_load(current_yaml)
            if not isinstance(doc, dict):
                st.error("Could not parse the contract YAML — unexpected format.")
                return
        except yaml.YAMLError:
            st.error("Could not parse the contract YAML.")
            return

        _db_col_to_label: dict[str, str] = {
            "critical_data_element": "Critical Data Element",
            "excluded_data_element": "Excluded Data Element",
            "pii_flag":              "PII",
            "description":           "Description",
            "data_source":           "Data Source",
            "source_system":         "Source System",
            "source_process":        "Source Process",
            "business_domain":       "Business Domain",
            "stakeholder_group":     "Stakeholder Group",
            "transform_level":       "Transform Level",
            "aggregation_level":     "Aggregation Level",
            "data_product":          "Data Product",
        }

        pending_key = f"dc_pending:{table_group_id}"
        pending = st.session_state.get(pending_key, {})

        for db_col, new_val in updates.items():
            old_val = gov.get(db_col)
            norm_new = new_val if new_val != "" else None
            norm_old = old_val if old_val != "" else None
            if norm_new == norm_old:
                continue
            label = _db_col_to_label.get(db_col)
            if not label:
                continue
            _patch_yaml_governance(doc, table_name, col_name, label, new_val)
            pending = _apply_pending_governance_edit(pending, table_name, col_name, label, new_val)

        patched_yaml = yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
        st.session_state[yaml_key] = patched_yaml
        st.session_state[pending_key] = pending
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
    icon        = _MONITOR_ICON.get(test_type, "📡")
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
        st.markdown(f"**Last Run** &nbsp; {html.escape(str(last['executedAt']))}")
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
    status_icon = _STATUS_ICON.get(status, "⏳")
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
    for col_st, (label, value) in zip(cols, meta, strict=False):
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
            st.session_state[f"dc_select_term:{table_group_id}"] = rule_id
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
    yaml_key: str,  # noqa: ARG001
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
            _hygiene_key = f"profiling|Hygiene|{term.get('value', '')}|{table_name}|{col_name}"
            st.session_state[f"dc_select_term:{table_group_id}"] = _hygiene_key
            safe_rerun()
        if close_col.button("Close", key="hygiene_close", use_container_width=True):
            safe_rerun()
        return
    if can_delete:
        del_col, close_col = st.columns(2)
        if del_col.button("Delete term from contract", key="term_read_delete", use_container_width=True):
            _term_key = f"{src}|{term_name}|{term.get('value', '')}|{table_name}|{col_name}"
            st.session_state[f"dc_select_term:{table_group_id}"] = _term_key
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
        new_cde: bool   = st.checkbox("Mark as Critical Data Element", value=bool(current_value))
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
        _gov_key = f"governance|{term_name}|{current_value}|{table_name}|{col_name}"
        st.session_state[f"dc_select_term:{table_group_id}"] = _gov_key
        safe_rerun()


# ---------------------------------------------------------------------------
# Quality rule edit dialog
# ---------------------------------------------------------------------------

@st.dialog("Edit Quality Rule", width="small")
def _edit_rule_dialog(rule: dict, table_group_id: str, yaml_key: str, snapshot_suite_id: str | None = None) -> None:  # noqa: ARG001
    rule_id   = str(rule.get("id", ""))
    test_name = rule.get("name") or rule.get("type") or "Test"

    live_info   = _fetch_test_live_info(rule_id) if rule_id else {}
    live_status = live_info.get("status", "")

    st.markdown(f"**{test_name}**")
    if rule.get("element"):
        st.caption(f"Element: `{rule['element']}`")
    if live_status:
        icon = _STATUS_ICON.get(live_status, "")
        st.caption(f"Last result: {icon} {live_status}")

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

    severity_options = [None, "Log", "Warning", "Fail"]
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
        st.session_state[f"dc_select_term:{table_group_id}"] = rule_id
        safe_rerun()


# ---------------------------------------------------------------------------
# Regenerate dialog
# ---------------------------------------------------------------------------

@st.dialog("Regenerate Contract", width="small")
def _regenerate_dialog(contract_id: str, table_group_id: str, current_version: int | None, pending_ct: int = 0) -> None:
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
            f"You have **{pending_ct} unsaved {'edit' if pending_ct == 1 else 'edits'}** that will be discarded. "
            "Save a new version first if you want to keep them.",
            icon="⚠️",
        )
        confirmed = st.checkbox("I understand — discard my pending edits and regenerate")

    # Show snapshot suite name that will be created
    _tg_regen = TableGroup.get_minimal(table_group_id)
    _tg_name_regen = getattr(_tg_regen, "table_groups_name", "") or table_group_id
    _snapshot_suite_name_regen = f"[Contract v{next_ver}] {_tg_name_regen}"
    st.info(
        f"A new test suite will be created:\n\n"
        f"**{_snapshot_suite_name_regen}**\n\n"
        f"It will contain a copy of all tests currently in scope for this contract. "
        f"Tests in this suite can only be managed from the Data Contract UI.",
        icon="ℹ️",
    )

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
            new_version = save_contract_version(contract_id, table_group_id, fresh_yaml, label=label or None)

        # Create the snapshot test suite.  On ANY failure, roll back the just-saved
        # version so the DB is not left with an orphaned row that has no snapshot suite.
        try:
            create_contract_snapshot_suite(table_group_id, new_version)
        except Exception as snap_err:
            try:
                rollback_contract_version(contract_id, new_version)
            except Exception:
                LOG.exception("Failed to roll back orphaned contract version %d", new_version)
            if isinstance(snap_err, ValueError):
                st.error(f"No in-scope tests found — add tests to at least one contract suite before saving. ({snap_err})")
            else:
                st.error(f"Snapshot suite creation failed: {snap_err}")
            return

        st.success(f"Saved as version {new_version}.")
        _clear_contract_cache(contract_id)
        safe_rerun()
    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Update version dialog (in-place, no version bump)
# ---------------------------------------------------------------------------

@st.dialog("Save Changes", width="small")
def _update_version_dialog(
    contract_id: str,
    table_group_id: str,
    pending: dict,
    current_yaml: str,
    current_version: int,
    snapshot_suite_id: str | None = None,
) -> None:
    gov_edits  = pending.get("governance", [])
    test_edits = pending.get("tests", [])
    deletions  = pending.get("deletions", [])

    st.markdown(f"**Update version {current_version} in place**")
    st.info("These changes will be saved to the **current version** — no new version number will be created. To snapshot a new version, cancel and click **Save version** without pending edits.", icon=":material/edit_note:")

    if gov_edits or test_edits or deletions:
        st.markdown("**Changes to save:**")
        for e in gov_edits:
            st.markdown(f"  · {html.escape(e['table'])}.{html.escape(e['col'])} — {html.escape(e['field'])}: {html.escape(str(e['value']))}")
        for e in test_edits:
            label = "deleted" if e.get("_removed") else "updated"
            st.markdown(f"  · Test `{e['rule_id'][:8]}…` {label}")
        for e in deletions:
            st.markdown(f"  · Deleted {html.escape(e.get('table', ''))}.{html.escape(e.get('col', ''))} — {html.escape(e.get('name', ''))}")

    st.divider()
    save_col, cancel_col = st.columns(2)

    if save_col.button("Save", type="primary", use_container_width=True):
        try:
            with st.spinner("Saving…"):
                _persist_pending_edits(table_group_id, pending)
                update_contract_version(contract_id, current_version, current_yaml)

                # Mirror test mutations into the snapshot suite so the snapshot stays
                # in sync with test_definitions after the in-place update.
                if snapshot_suite_id:
                    updated_ids = [
                        e["rule_id"] for e in test_edits
                        if not e.get("_removed")
                    ]
                    deleted_ids = [
                        e["rule_id"] for e in test_edits
                        if e.get("_removed")
                    ]
                    if updated_ids or deleted_ids:
                        try:
                            sync_import_to_snapshot_suite(snapshot_suite_id, [], updated_ids, deleted_ids)
                        except Exception:
                            LOG.exception(
                                "_update_version_dialog: failed to sync to snapshot suite %s",
                                snapshot_suite_id,
                            )

            st.success(f"Version {current_version} updated.")
            _clear_contract_cache(contract_id)
            safe_rerun()
        except Exception as exc:
            st.error(f"Save failed: {exc}")

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Save version dialog
# ---------------------------------------------------------------------------

@st.dialog("Save New Version", width="small")
def _save_version_dialog(
    contract_id: str,
    table_group_id: str,
    pending: dict,
    current_yaml: str,
    current_version: int | None,
) -> None:
    gov_edits  = pending.get("governance", [])
    test_edits = pending.get("tests", [])
    next_ver   = (current_version + 1) if current_version is not None else 0

    st.markdown(f"**Create new version {next_ver}**")
    if current_version is not None:
        st.info(f"This creates a permanent, timestamped snapshot of the contract. Version {current_version} remains available as a historical record.", icon=":material/bookmark_add:")

    if gov_edits or test_edits:
        st.markdown("**Changes to include:**")
        for e in gov_edits:
            st.markdown(f"  · {html.escape(e['table'])}.{html.escape(e['col'])} — {html.escape(e['field'])}: {html.escape(str(e['value']))}")
        for e in test_edits:
            st.markdown(f"  · Test `{e['rule_id'][:8]}…` updated")
    else:
        st.info("No edits pending — this will snapshot the current contract state without changes.", icon="ℹ️")

    # Resolve table group name for snapshot suite warning
    _tg = TableGroup.get_minimal(table_group_id)
    _tg_name = getattr(_tg, "table_groups_name", "") or table_group_id
    _snapshot_suite_name = f"[Contract v{next_ver}] {_tg_name}"
    st.info(
        f"A new test suite will be created:\n\n"
        f"**{_snapshot_suite_name}**\n\n"
        f"It will contain a copy of all tests currently in scope for this contract. "
        f"Tests in this suite can only be managed from the Data Contract UI.",
        icon="ℹ️",
    )

    label = st.text_input("Label (optional)", placeholder="e.g. Added PII tests for orders table")
    st.divider()
    save_col, cancel_col = st.columns(2)

    if save_col.button("Save Version", type="primary", use_container_width=True):
        try:
            with st.spinner("Saving…"):
                # 1. Apply all pending edits to DB (governance + tests)
                _persist_pending_edits(table_group_id, pending)

                # 2. Save snapshot from the in-memory patched YAML (not a fresh export)
                new_version = save_contract_version(contract_id, table_group_id, current_yaml, label=label or None)

            # 3. Create the snapshot test suite.  On ANY failure, roll back the
            # just-saved version so the DB is not left with an orphaned row that
            # has no snapshot suite.
            try:
                create_contract_snapshot_suite(table_group_id, new_version)
            except Exception as snap_err:
                try:
                    rollback_contract_version(contract_id, new_version)
                except Exception:
                    LOG.exception("Failed to roll back orphaned contract version %d", new_version)
                if isinstance(snap_err, ValueError):
                    st.error(f"No in-scope tests found — add tests to at least one contract suite before saving. ({snap_err})")
                else:
                    st.error(f"Snapshot suite creation failed: {snap_err}")
                return

            st.success(f"Saved as version {new_version}.")
            _clear_contract_cache(contract_id)
            safe_rerun()

        except ValueError as exc:
            st.error(str(exc))
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
    contract_id: str,
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
        pending = st.session_state.get(f"dc_pending:{contract_id}", {})
        # table_group_id is not available here; _save_version_dialog needs it.
        # We pass contract_id twice as a fallback — callers that need table_group_id
        # should pre-stage it in session state if needed.
        _tg_id = st.session_state.get(f"dc_tg_id:{contract_id}", contract_id)
        _save_version_dialog(contract_id, _tg_id, pending, current_yaml, version_record.get("version"))


# ---------------------------------------------------------------------------
# Cancel all changes dialog
# ---------------------------------------------------------------------------

@st.dialog("Discard Changes", width="small")
def cancel_all_changes_dialog(
    contract_id: str,
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
        st.session_state.pop(f"dc_pending:{contract_id}", None)
        st.session_state[f"dc_yaml:{contract_id}"] = original_yaml
        safe_rerun()
    if back_col.button("Go back", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Delete version dialog
# ---------------------------------------------------------------------------

@st.dialog("Delete Contract Version", width="small")
@with_database_session
def _delete_version_dialog(table_group_id: str, version: int) -> None:
    """Confirm and delete a saved contract version and its snapshot suite."""
    schema = get_tg_schema()

    # Fetch version info and snapshot suite details
    ver_rows = fetch_dict_from_db(
        f"""
        SELECT dc.snapshot_suite_id::text AS snapshot_suite_id,
               dc.label,
               dc.saved_at
        FROM {schema}.data_contracts dc
        WHERE dc.table_group_id = CAST(:tg_id AS uuid)
          AND dc.version = :version
        """,
        params={"tg_id": table_group_id, "version": version},
    )

    if not ver_rows:
        st.error(f"Contract version {version} not found.")
        return

    ver_info = dict(ver_rows[0])
    snapshot_suite_id: str | None = ver_info.get("snapshot_suite_id") or None
    label_str = ver_info.get("label") or "no label"
    saved_at = ver_info.get("saved_at")
    saved_str = saved_at.strftime("%b %d, %Y") if saved_at else "unknown date"

    # Fetch snapshot suite test count if applicable
    test_count = 0
    suite_name = ""
    if snapshot_suite_id:
        count_rows = fetch_dict_from_db(
            f"SELECT COUNT(*) AS ct FROM {schema}.test_definitions WHERE test_suite_id = CAST(:sid AS uuid)",
            params={"sid": snapshot_suite_id},
        )
        test_count = int(count_rows[0]["ct"] or 0) if count_rows else 0

        suite_rows = fetch_dict_from_db(
            f"SELECT test_suite FROM {schema}.test_suites WHERE id = CAST(:sid AS uuid)",
            params={"sid": snapshot_suite_id},
        )
        suite_name = suite_rows[0]["test_suite"] if suite_rows else f"[Contract v{version}]"

    # Check if this is the latest version
    all_versions = list_contract_versions(table_group_id)
    latest_version = all_versions[0]["version"] if all_versions else version
    is_latest_version = (version == latest_version)
    prev_version = all_versions[1]["version"] if len(all_versions) > 1 and is_latest_version else None

    st.markdown(f"**Delete contract v{version}?**")
    st.divider()

    st.markdown(
        f"This will permanently delete:\n\n"
        f"- Contract version v{version} ({label_str}, saved {saved_str})"
    )
    if snapshot_suite_id:
        st.markdown(f'- Test suite **"{suite_name}"** and all {test_count} tests in it')

    st.markdown("\n**This action cannot be undone.**")

    if is_latest_version and prev_version is not None:
        st.error(
            f"You are deleting the **latest** version. After deletion, "
            f"v{prev_version} will become the active contract. "
            f"All pending changes will be lost.",
            icon=":material/dangerous:",
        )

    st.divider()
    confirm_input = st.text_input("Type DELETE to confirm", placeholder="DELETE")
    is_confirmed = confirm_input == "DELETE"

    confirm_col, cancel_col = st.columns(2)
    if confirm_col.button("Delete", type="primary", use_container_width=True, disabled=not is_confirmed):
        try:
            delete_contract_version(table_group_id, version)
            _clear_contract_cache(table_group_id, also_anomalies=True)
            # Clear version query param if this was the viewed version
            if "version" in st.query_params:
                del st.query_params["version"]
            safe_rerun()
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            LOG.exception("_delete_version_dialog: failed to delete version %d", version)
            st.error(f"Delete failed: {exc}")

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


# ---------------------------------------------------------------------------
# Import YAML confirmation
# ---------------------------------------------------------------------------

@st.dialog("Import Contract from YAML", width="small")
def _confirm_import_dialog(
    preview: ContractDiff,
    yaml_content: str,
    table_group_id: str,
    snapshot_suite_id: str | None,
    import_key: str,
) -> None:
    """Show a preview of the import diff and ask the user to confirm."""
    st.subheader("Import Contract from YAML")

    if preview.has_errors:
        for err in preview.errors:
            st.error(err, icon=":material/dangerous:")
        if st.button("Close", use_container_width=True):
            safe_rerun()
        return

    # ── Quality rule summary ──────────────────────────────────────────────
    total_rules = (
        len(preview.test_inserts)
        + len(preview.test_updates)
        + preview.no_change_rules
        + preview.skipped_rules
    )
    accepted = len(preview.test_inserts) + len(preview.test_updates) + preview.no_change_rules
    rejected = preview.skipped_rules

    st.markdown("**Quality Rules**")
    col_acc, col_rej = st.columns(2)
    col_acc.metric("Accepted", accepted, help="Rules that will create, update, or match an existing test")
    col_rej.metric("Skipped", rejected, help="Rules with a missing/duplicate id or an immutable field change")

    if total_rules > 0:
        rows = []
        if preview.test_inserts:
            n = len(preview.test_inserts)
            rows.append(f"- **{n}** new {'test' if n == 1 else 'tests'} to create")
        if preview.test_updates:
            n = len(preview.test_updates)
            rows.append(f"- **{n}** existing {'test' if n == 1 else 'tests'} to update")
        if preview.no_change_rules:
            n = preview.no_change_rules
            rows.append(f"- **{n}** {'test' if n == 1 else 'tests'} unchanged")
        if rejected:
            rows.append(f"- **{rejected}** {'rule' if rejected == 1 else 'rules'} skipped")
        st.markdown("\n".join(rows))

    # ── Other changes ─────────────────────────────────────────────────────
    other_ct = len(preview.governance_updates) + len(preview.contract_updates) + len(preview.table_group_updates)
    if other_ct:
        st.divider()
        st.markdown("**Other Changes**")
        other_rows = []
        if preview.governance_updates:
            n = len(preview.governance_updates)
            other_rows.append(f"- **{n}** column governance {'update' if n == 1 else 'updates'}")
        metadata_ct = len(preview.contract_updates) + len(preview.table_group_updates)
        if metadata_ct:
            other_rows.append(f"- **{metadata_ct}** contract metadata {'field' if metadata_ct == 1 else 'fields'}")
        st.markdown("\n".join(other_rows))

    # ── Warnings ─────────────────────────────────────────────────────────
    rule_warnings = [w for w in preview.warnings if "not in YAML" not in w]
    if rule_warnings:
        st.divider()
        n = len(rule_warnings)
        with st.expander(f"⚠ {n} {'warning' if n == 1 else 'warnings'}", expanded=False):
            for w in rule_warnings:
                st.warning(w, icon="⚠️")

    # ── Orphaned tests note ───────────────────────────────────────────────
    if preview.orphaned_ids:
        n = len(preview.orphaned_ids)
        st.info(
            f"{n} {'test' if n == 1 else 'tests'} in the table group are not in this YAML and will not be affected.",
            icon=":material/info:",
        )

    st.divider()
    confirm_col, cancel_col = st.columns(2)

    if confirm_col.button("Confirm Import", type="primary", use_container_width=True):
        try:
            diff = run_import_contract(yaml_content, table_group_id)
            st.session_state[import_key] = {
                "diff": diff,
                "original_yaml": yaml_content,
            }
            if not diff.has_errors and snapshot_suite_id:
                created_ids = list(diff.new_id_by_index.values()) if diff.new_id_by_index else []
                updated_ids = [str(u["id"]) for u in (diff.test_updates or []) if u.get("id")]
                if created_ids or updated_ids:
                    try:
                        sync_import_to_snapshot_suite(snapshot_suite_id, created_ids, updated_ids, [])
                    except Exception:
                        LOG.exception("_confirm_import_dialog: failed to sync to snapshot suite %s", snapshot_suite_id)
            if not diff.has_errors:
                _clear_contract_cache(table_group_id, also_anomalies=True)
        except Exception as exc:
            st.session_state[import_key] = {"error": str(exc)}
        safe_rerun()

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()


@st.dialog("Import Contract from YAML", width="small")
def _import_yaml_dialog(
    table_group_id: str,
    snapshot_suite_id: str | None,
    import_key: str,
) -> None:
    """Toolbar-triggered import dialog: file upload + dry-run preview + confirm."""
    uploaded = st.file_uploader(
        "Upload ODCS YAML",
        type=["yaml", "yml"],
        key=f"dc_dlg_upload:{table_group_id}",
    )

    if uploaded is None:
        st.caption("Select a YAML file to preview changes before importing.")
        if st.button("Cancel", use_container_width=True):
            safe_rerun()
        return

    yaml_content: str = uploaded.read().decode("utf-8")

    # Compute dry-run preview
    with st.spinner("Analysing YAML\u2026"):
        try:
            preview: ContractDiff = run_import_contract(yaml_content, table_group_id, dry_run=True)
        except Exception as exc:
            st.error(f"Could not parse YAML: {exc}", icon=":material/dangerous:")
            if st.button("Close", use_container_width=True):
                safe_rerun()
            return

    if preview.has_errors:
        for err in preview.errors:
            st.error(err, icon=":material/dangerous:")
        if st.button("Close", use_container_width=True):
            safe_rerun()
        return

    # ── Quality rule summary ──────────────────────────────────────────────
    total_rules = (
        len(preview.test_inserts)
        + len(preview.test_updates)
        + preview.no_change_rules
        + preview.skipped_rules
    )
    accepted = len(preview.test_inserts) + len(preview.test_updates) + preview.no_change_rules
    rejected = preview.skipped_rules

    st.markdown("**Quality Rules**")
    col_acc, col_rej = st.columns(2)
    col_acc.metric("Accepted", accepted, help="Rules that will create, update, or match an existing test")
    col_rej.metric("Skipped", rejected, help="Rules with a missing/duplicate id or an immutable field change")

    if total_rules > 0:
        rows = []
        if preview.test_inserts:
            n = len(preview.test_inserts)
            rows.append(f"- **{n}** new {'test' if n == 1 else 'tests'} to create")
        if preview.test_updates:
            n = len(preview.test_updates)
            rows.append(f"- **{n}** existing {'test' if n == 1 else 'tests'} to update")
        if preview.no_change_rules:
            n = preview.no_change_rules
            rows.append(f"- **{n}** {'test' if n == 1 else 'tests'} unchanged")
        if rejected:
            rows.append(f"- **{rejected}** {'rule' if rejected == 1 else 'rules'} skipped")
        st.markdown("\n".join(rows))

    # ── Other changes ─────────────────────────────────────────────────────
    other_ct = len(preview.governance_updates) + len(preview.contract_updates) + len(preview.table_group_updates)
    if other_ct:
        st.divider()
        st.markdown("**Other Changes**")
        other_rows = []
        if preview.governance_updates:
            n = len(preview.governance_updates)
            other_rows.append(f"- **{n}** column governance {'update' if n == 1 else 'updates'}")
        metadata_ct = len(preview.contract_updates) + len(preview.table_group_updates)
        if metadata_ct:
            other_rows.append(f"- **{metadata_ct}** contract metadata {'field' if metadata_ct == 1 else 'fields'}")
        st.markdown("\n".join(other_rows))

    # ── Warnings ─────────────────────────────────────────────────────────
    rule_warnings = [w for w in preview.warnings if "not in YAML" not in w]
    if rule_warnings:
        st.divider()
        n = len(rule_warnings)
        with st.expander(f"\u26a0 {n} {'warning' if n == 1 else 'warnings'}", expanded=False):
            for w in rule_warnings:
                st.warning(w, icon="\u26a0\ufe0f")

    # ── Orphaned tests note ───────────────────────────────────────────────
    if preview.orphaned_ids:
        n = len(preview.orphaned_ids)
        st.info(
            f"{n} {'test' if n == 1 else 'tests'} in the table group are not in this YAML and will not be affected.",
            icon=":material/info:",
        )

    st.divider()
    confirm_col, cancel_col = st.columns(2)

    if confirm_col.button("Confirm Import", type="primary", use_container_width=True):
        try:
            diff = run_import_contract(yaml_content, table_group_id)
            st.session_state[import_key] = {
                "diff": diff,
                "original_yaml": yaml_content,
            }
            if not diff.has_errors and snapshot_suite_id:
                created_ids = list(diff.new_id_by_index.values()) if diff.new_id_by_index else []
                updated_ids = [str(u["id"]) for u in (diff.test_updates or []) if u.get("id")]
                if created_ids or updated_ids:
                    try:
                        sync_import_to_snapshot_suite(snapshot_suite_id, created_ids, updated_ids, [])
                    except Exception:
                        LOG.exception("_import_yaml_dialog: failed to sync to snapshot suite %s", snapshot_suite_id)
            if not diff.has_errors:
                _clear_contract_cache(table_group_id, also_anomalies=True)
        except Exception as exc:
            st.session_state[import_key] = {"error": str(exc)}
        safe_rerun()

    if cancel_col.button("Cancel", use_container_width=True):
        safe_rerun()
