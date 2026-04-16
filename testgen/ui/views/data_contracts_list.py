"""
Data Contracts list page — project-scoped card grid.

One card per contract, grouped by table group, 3-column grid.
Only place to create or delete contracts.
"""
from __future__ import annotations

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

# Status → (strip_color_hex, badge_label, badge_color_class)
_STATUS_STYLE: dict[str, tuple[str, str, str]] = {
    "Passing": ("#22c55e", "✓ Passing", "green"),
    "Warning": ("#f59e0b", "⚠ Warning", "orange"),
    "Failing": ("#ef4444", "✗ Failing", "red"),
    "No Run":  ("#cbd5e1", "○ No Run",  "gray"),
}


def _status_strip(status: str) -> str:
    color = _STATUS_STYLE.get(status, _STATUS_STYLE["No Run"])[0]
    return f'<div style="height:4px;background:{color};border-radius:4px 4px 0 0;margin:-8px -8px 8px -8px"></div>'


def _status_badge(status: str) -> str:
    _, label, color = _STATUS_STYLE.get(status, _STATUS_STYLE["No Run"])
    return f":{color}[{label}]"


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
        toolbar_left, toolbar_right = st.columns([6, 1])
        with toolbar_left:
            st.caption(
                f"{len(contracts)} contract{'s' if len(contracts) != 1 else ''} · "
                f"{tg_count} table group{'s' if tg_count != 1 else ''}"
            )
        with toolbar_right:
            if st.button("+ New Contract", type="primary", use_container_width=True):
                create_contract_wizard(project_code=project_code)

        if not contracts:
            st.info("No contracts yet. Click **+ New Contract** to create one.", icon=":material/contract:")
            return

        # ── Cards grouped by table group ───────────────────────────
        sorted_contracts = sorted(contracts, key=lambda c: (c["table_group_name"], c["name"]))
        for tg_name, group_iter in groupby(sorted_contracts, key=lambda c: c["table_group_name"]):
            group = list(group_iter)
            st.markdown(f"**{tg_name}**")
            cols = st.columns(3)
            for idx, contract in enumerate(group):
                col = cols[idx % 3]
                with col:
                    self._render_card(contract)

    def _render_card(self, contract: dict) -> None:
        """Render one contract card."""
        contract_id   = contract["contract_id"]
        name          = contract["name"]
        is_active     = contract["is_active"]
        status        = contract["status"] if is_active else "Inactive"
        version       = contract["version"]
        term_count    = contract["term_count"]
        test_count    = contract["test_count"]
        version_count = contract["version_count"]

        # Inactive overrides
        if not is_active:
            strip_color = "#94a3b8"
            badge_md = ":gray[Inactive]"
        else:
            strip_color = _STATUS_STYLE.get(status, _STATUS_STYLE["No Run"])[0]
            _, badge_label, badge_color = _STATUS_STYLE.get(status, _STATUS_STYLE["No Run"])
            badge_md = f":{badge_color}[{badge_label}]"

        with st.container(border=True):
            # Color strip (4px top border via markdown)
            st.markdown(
                f'<div style="height:4px;background:{strip_color};'
                f'border-radius:3px;margin-bottom:6px"></div>',
                unsafe_allow_html=True,
            )

            # Name + status badge
            name_col, badge_col = st.columns([3, 2])
            with name_col:
                if st.button(
                    name,
                    key=f"dc_list_card_btn:{contract_id}",
                    type="tertiary",
                    help="Open contract detail",
                ):
                    Router().queue_navigation(to="data-contract", with_args={"contract_id": contract_id})
            with badge_col:
                st.markdown(badge_md)

            # Stats row
            v_col, t_col, tst_col = st.columns(3)
            v_label   = f"v{version}" if version >= 0 else "—"
            v_col.metric("Version", v_label)
            t_col.metric("Terms", str(term_count))
            tst_col.metric("Tests", str(test_count))

            # Footer: deactivate/reactivate + delete
            act_col, del_col = st.columns([1, 1])
            with act_col:
                if is_active:
                    if st.button("Deactivate", key=f"dc_list_deact:{contract_id}",
                                 type="secondary", use_container_width=True):
                        set_contract_active(contract_id, False)
                        safe_rerun()
                else:
                    if st.button("Reactivate", key=f"dc_list_react:{contract_id}",
                                 type="secondary", use_container_width=True):
                        set_contract_active(contract_id, True)
                        safe_rerun()
            with del_col:
                if st.button("Delete", key=f"dc_list_del:{contract_id}",
                             use_container_width=True):
                    _delete_contract_dialog(contract_id, name, version_count)
