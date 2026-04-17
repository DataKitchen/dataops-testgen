"""
Data Contracts list page — project-scoped card grid.

One card per contract, grouped by table group, 3-column grid.
Only place to create or delete contracts.
"""
from __future__ import annotations

import datetime
import html
import typing
from itertools import groupby

import streamlit as st

from testgen.commands.contract_management import delete_contract, get_contract, set_contract_active
from testgen.commands.contract_versions import get_snapshot_suite_ids_for_contract
from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.menu import MenuItem
from testgen.ui.navigation.page import Page
from testgen.ui.navigation.router import Router
from testgen.ui.queries.data_contract_list_queries import fetch_contracts_for_project
from testgen.ui.services.rerun_service import safe_rerun
from testgen.ui.session import session

PAGE_TITLE = "Data Contracts"
PAGE_ICON = "contract"

# Status → (badge_label, badge_color_class)
_STATUS_STYLE: dict[str, tuple[str, str]] = {
    "Passing": ("✓ Passing", "green"),
    "Warning": ("⚠ Warning", "orange"),
    "Failing": ("✗ Failing", "red"),
    "No Run":  ("○ No Run",  "gray"),
}

_BADGE_HEX: dict[str, str] = {"green": "#22c55e", "orange": "#f59e0b", "red": "#ef4444", "gray": "#94a3b8"}



def _color_bar_html(passed_ct: int, warning_ct: int, failed_ct: int) -> str:
    """Return the proportional color-strip HTML for a contract card."""
    total_run = passed_ct + warning_ct + failed_ct
    if total_run == 0:
        return '<div style="height:6px;background:#cbd5e1;border-radius:3px;margin-bottom:10px"></div>'
    segs = ""
    if passed_ct:
        segs += f'<div style="flex:{passed_ct};background:#22c55e"></div>'
    if warning_ct:
        segs += f'<div style="flex:{warning_ct};background:#f59e0b"></div>'
    if failed_ct:
        segs += f'<div style="flex:{failed_ct};background:#ef4444"></div>'
    return f'<div style="height:6px;display:flex;border-radius:3px;overflow:hidden;margin-bottom:10px">{segs}</div>'


def _format_last_run(dt: object) -> str:
    """Return a human-readable relative time string for a datetime, or 'Never'."""
    if dt is None:
        return "Never"
    if hasattr(dt, "date"):  # already a datetime
        now = datetime.datetime.now(tz=dt.tzinfo)
        delta = now - dt
        days = delta.days
        if days == 0:
            return "Today"
        if days == 1:
            return "Yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            weeks = days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        if days < 365:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        years = days // 365
        return f"{years} year{'s' if years != 1 else ''} ago"
    return str(dt)


@st.dialog("Delete Contract")
def _delete_contract_dialog(contract_id: str, contract_name: str, version_count: int) -> None:
    st.warning(
        f"Delete **{contract_name}** and all {version_count} saved "
        f"{'version' if version_count == 1 else 'versions'}? This cannot be undone.",
        icon="⚠️",
    )
    col1, col2 = st.columns(2)
    if col1.button("Delete", type="primary", use_container_width=True):
        contract = get_contract(contract_id)
        if contract:
            snap_ids = get_snapshot_suite_ids_for_contract(contract_id)
            delete_contract(contract_id, contract["test_suite_id"], snap_ids)
        safe_rerun()
    if col2.button("Cancel", use_container_width=True):
        safe_rerun()


class DataContractsListPage(Page):
    path = "data-contracts"
    can_activate: typing.ClassVar = [
        lambda: session.auth.is_logged_in,
        lambda: "project_code" in st.query_params,
    ]
    menu_item = MenuItem(
        icon=PAGE_ICON,
        label=PAGE_TITLE,
        section="Data Quality Testing",
        order=1,
    )

    def render(self, project_code: str, **_kwargs: typing.Any) -> None:
        from testgen.ui.views.dialogs.data_contract_dialogs import create_contract_wizard

        testgen.page_header(PAGE_TITLE, "data-contracts/")

        contracts = fetch_contracts_for_project(project_code)

        # ── Toolbar ────────────────────────────────────────────────
        tg_count = len({c["table_group_id"] for c in contracts})
        toolbar_left, toolbar_right = st.columns([5, 1])
        with toolbar_left:
            st.caption(
                f"{len(contracts)} contract{'s' if len(contracts) != 1 else ''} · "
                f"{tg_count} table group{'s' if tg_count != 1 else ''}"
            )
        with toolbar_right:
            if st.button("+ New Contract", type="secondary"):
                create_contract_wizard(project_code=project_code)

        if not contracts:
            st.info("No contracts yet. Use **+ New Contract** to create one.", icon=":material/contract:")
            if st.button("+ New Contract", key="dc_list_empty_new", type="primary"):
                create_contract_wizard(project_code=project_code)
            return

        # ── Cards grouped by table group ───────────────────────────
        sorted_contracts = sorted(contracts, key=lambda c: (c["table_group_name"], c["name"]))
        for group_idx, (tg_name, group_iter) in enumerate(groupby(sorted_contracts, key=lambda c: c["table_group_name"])):
            group = list(group_iter)
            if group_idx > 0:
                st.divider()
            st.markdown(f"**{tg_name}**")
            cols = st.columns(3)
            for idx, contract in enumerate(group):
                col = cols[idx % 3]
                with col:
                    self._render_card(contract)

    def _render_card(self, contract: dict) -> None:
        """Render one contract card. The card body is a single anchor — whole card is clickable."""
        contract_id   = contract["contract_id"]
        name          = contract["name"]
        is_active     = contract["is_active"]
        status        = contract["status"] if is_active else "Inactive"
        version       = contract["version"]
        term_count    = contract["term_count"]
        test_count    = contract["test_count"]
        version_count = contract["version_count"]
        table_count   = contract["table_count"]
        last_run_at   = contract.get("last_run_at")

        if not is_active:
            strip_html = '<div style="height:6px;background:#94a3b8;border-radius:3px;margin-bottom:10px"></div>'
            badge_html = '<span style="color:var(--text-color);opacity:.6">Inactive</span>'
        else:
            passed_ct  = int(contract.get("passed_ct")  or 0)
            warning_ct = int(contract.get("warning_ct") or 0)
            failed_ct  = int(contract.get("failed_ct")  or 0)
            strip_html = _color_bar_html(passed_ct, warning_ct, failed_ct)
            badge_label, badge_color = _STATUS_STYLE.get(status, _STATUS_STYLE["No Run"])
            hex_color  = _BADGE_HEX.get(badge_color, "#94a3b8")
            badge_html = f'<span style="color:{hex_color};font-size:.85em;font-weight:600">{badge_label}</span>'

        v_label = f"v{version}" if version >= 0 else "—"
        last_run_str = _format_last_run(last_run_at)
        detail_url = f"/data-contract?contract_id={contract_id}"
        name_escaped = html.escape(name, quote=True)

        with st.container(border=True):
            # Card body: entire area is a single <a> link so clicking anywhere navigates.
            st.markdown(f"""
<a href="{detail_url}" target="_self" style="display:block;text-decoration:none;color:inherit">
  {strip_html}
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <span style="font-weight:600;font-size:1em">{name_escaped}</span>
    {badge_html}
  </div>
  <div style="display:flex;gap:8px;margin-bottom:6px">
    <div style="flex:1;text-align:left">
      <div style="font-size:.75em;opacity:.6;margin-bottom:2px">Version</div>
      <div style="font-size:1.1em;font-weight:600">{v_label}</div>
    </div>
    <div style="flex:1;text-align:left">
      <div style="font-size:.75em;opacity:.6;margin-bottom:2px">Tables</div>
      <div style="font-size:1.1em;font-weight:600">{table_count}</div>
    </div>
    <div style="flex:1;text-align:left">
      <div style="font-size:.75em;opacity:.6;margin-bottom:2px">Terms</div>
      <div style="font-size:1.1em;font-weight:600">{term_count}</div>
    </div>
    <div style="flex:1;text-align:left">
      <div style="font-size:.75em;opacity:.6;margin-bottom:2px">Tests</div>
      <div style="font-size:1.1em;font-weight:600">{test_count}</div>
    </div>
  </div>
  <div style="font-size:.73em;opacity:.5;margin-bottom:8px">Last run: {last_run_str}</div>
</a>
""", unsafe_allow_html=True)

            # Footer buttons — outside the <a> link so they act independently
            if is_active:
                # Only Delete — right-aligned
                _, del_col = st.columns([2, 1])
                with del_col:
                    if st.button("Delete", key=f"dc_list_del:{contract_id}",
                                 use_container_width=True):
                        _delete_contract_dialog(contract_id, name, version_count)
            else:
                # Reactivate + Delete side by side
                react_col, del_col = st.columns([1, 1])
                with react_col:
                    if st.button("Reactivate", key=f"dc_list_react:{contract_id}",
                                 type="secondary", use_container_width=True):
                        set_contract_active(contract_id, True)
                        safe_rerun()
                with del_col:
                    if st.button("Delete", key=f"dc_list_del:{contract_id}",
                                 use_container_width=True):
                        _delete_contract_dialog(contract_id, name, version_count)
