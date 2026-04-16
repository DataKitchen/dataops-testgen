"""AppTest fixture for DataContractsListPage."""
from __future__ import annotations

import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import streamlit.components.v1 as _stv1
_stv1.declare_component = MagicMock(return_value=MagicMock())

if "testgen.ui.components.utils.component" not in sys.modules:
    sys.modules["testgen.ui.components.utils.component"] = MagicMock()

mock_tg_component = MagicMock()
if "testgen.ui.components.widgets.testgen_component" not in sys.modules:
    sys.modules["testgen.ui.components.widgets.testgen_component"] = mock_tg_component

import streamlit as st  # noqa: E402

PROJECT = "P1"
TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"

SAMPLE_CONTRACTS = [
    {
        "contract_id": "ccc111", "name": "customer_quality", "is_active": True,
        "table_group_id": TG_ID, "table_group_name": "customers_tg",
        "version": 3, "term_count": 42, "version_count": 4,
        "test_count": 12, "status": "Passing",
    },
    {
        "contract_id": "ccc222", "name": "orders_validation", "is_active": False,
        "table_group_id": TG_ID, "table_group_name": "customers_tg",
        "version": 1, "term_count": 10, "version_count": 2,
        "test_count": 5, "status": "No Run",
    },
]


def make_mock_auth() -> MagicMock:
    m = MagicMock()
    m.is_logged_in = True
    m.user_has_permission.return_value = True
    return m


def make_mock_version_svc() -> MagicMock:
    m = MagicMock()
    m.current = "5.0.0"
    m.latest = "5.0.0"
    return m


def render_list_page(contracts: list[dict] | None = None, project_code: str = PROJECT) -> None:
    from testgen.ui.views.data_contracts_list import DataContractsListPage

    _contracts = contracts if contracts is not None else SAMPLE_CONTRACTS
    mock_auth = make_mock_auth()
    mock_version_svc = make_mock_version_svc()

    patches = [
        patch("testgen.ui.views.data_contracts_list.fetch_contracts_for_project", return_value=_contracts),
        patch("testgen.ui.views.data_contracts_list.session", MagicMock(auth=mock_auth)),
        patch("testgen.ui.views.dialogs.data_contract_dialogs.create_contract_wizard", MagicMock()),
        patch("testgen.common.version_service.get_version", return_value=mock_version_svc),
        patch("testgen.ui.components.widgets.page.version_service",
              MagicMock(get_version=lambda: mock_version_svc)),
        patch("testgen.ui.components.widgets.page.testgen_component", mock_tg_component),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        page = DataContractsListPage.__new__(DataContractsListPage)
        page.router = MagicMock()
        page.render(project_code=project_code)


_mock_auth = make_mock_auth()
st.session_state["auth"] = _mock_auth
st.query_params["project_code"] = PROJECT

render_list_page()
