"""
Streamlit app script for AppTest — Data Contract delete version dialog.

Directly invokes _delete_version_dialog so it opens as a dialog on first run.
This works around the limitation that the JS 'DeleteVersionClicked' event
cannot fire in AppTest.
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Block custom component registration BEFORE any testgen UI imports.
# ---------------------------------------------------------------------------
import streamlit.components.v1 as _stv1
_stv1.declare_component = MagicMock(return_value=MagicMock())

if "testgen.ui.components.utils.component" not in sys.modules:
    sys.modules["testgen.ui.components.utils.component"] = MagicMock()

_mock_tg_component = MagicMock()
if "testgen.ui.components.widgets.testgen_component" not in sys.modules:
    sys.modules["testgen.ui.components.widgets.testgen_component"] = _mock_tg_component

import streamlit as st  # noqa: E402

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------
TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"

VERSION_0 = {
    "version": 0,
    "saved_at": datetime(2024, 1, 15, 10, 0, 0),
    "label": "Initial",
    "snapshot_suite_id": "bbbbbbbb-0000-0000-0000-000000000002",
}

VERSION_1 = {
    "version": 1,
    "saved_at": datetime(2024, 2, 20, 10, 0, 0),
    "label": "Updated",
    "snapshot_suite_id": "cccccccc-0000-0000-0000-000000000003",
}

_mock_version = MagicMock()
_mock_version.current = "5.0.0"
_mock_version.latest = "5.0.0"

_mock_auth = MagicMock()
_mock_auth.is_logged_in = True
_mock_auth.user_has_permission.return_value = True

# ---------------------------------------------------------------------------
# Mock fetch_dict_from_db: three sequential calls
#   1st: version info (snapshot_suite_id, label, saved_at)
#   2nd: test count
#   3rd: suite name
# ---------------------------------------------------------------------------
_fetch_call_count = [0]


def _mock_fetch(query: str, params: dict | None = None) -> list[dict]:
    _fetch_call_count[0] += 1
    n = _fetch_call_count[0]
    if n == 1:
        return [{"snapshot_suite_id": "cccccccc-0000-0000-0000-000000000003",
                 "label": "Updated",
                 "saved_at": datetime(2024, 2, 20, 10, 0, 0)}]
    elif n == 2:
        return [{"ct": 5}]
    elif n == 3:
        return [{"test_suite": "[Contract v1] Test Orders"}]
    return []


# ---------------------------------------------------------------------------
# Session / query params
# ---------------------------------------------------------------------------
st.session_state["auth"] = _mock_auth
st.query_params["table_group_id"] = TG_ID

# ---------------------------------------------------------------------------
# Directly invoke the dialog (opens it on first run)
# ---------------------------------------------------------------------------
_patches = [
    patch("testgen.ui.views.dialogs.data_contract_dialogs.fetch_dict_from_db", side_effect=_mock_fetch),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.list_contract_versions",
          return_value=[VERSION_1, VERSION_0]),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.delete_contract_version", MagicMock()),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.safe_rerun",
          MagicMock(side_effect=st.rerun)),
    patch("testgen.ui.views.dialogs.data_contract_dialogs._clear_contract_cache", MagicMock()),
    patch("testgen.common.version_service.get_version", return_value=_mock_version),
    patch("testgen.common.credentials.get_tg_schema", return_value="v5"),
    # with_database_session decorator wraps the dialog — bypass the DB session
    patch("testgen.common.models.database_session", MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False))),
]

with ExitStack() as _stack:
    for _p in _patches:
        _stack.enter_context(_p)

    # Reset call counter each script run (AppTest re-executes top-to-bottom)
    _fetch_call_count[0] = 0

    from testgen.ui.views.dialogs.data_contract_dialogs import _delete_version_dialog  # noqa: E402

    _delete_version_dialog(TG_ID, 1)
