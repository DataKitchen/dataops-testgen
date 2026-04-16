"""AppTest fixture for DataContractsListPage — empty state (no contracts)."""
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


def render_empty_list_page(project_code: str = PROJECT) -> None:
    from testgen.ui.views.data_contracts_list import DataContractsListPage

    mock_auth = make_mock_auth()
    mock_version_svc = make_mock_version_svc()

    patches = [
        patch("testgen.ui.views.data_contracts_list.fetch_contracts_for_project", return_value=[]),
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

render_empty_list_page()
