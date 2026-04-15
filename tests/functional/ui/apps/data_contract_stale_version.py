"""
Streamlit app script for AppTest — Data Contract stale-version flow.

Like saved_version but:
- TableGroup.contract_stale = True
- compute_staleness_diff returns a non-empty StaleDiff (triggers warning banner)
"""
from __future__ import annotations

from unittest.mock import MagicMock

from tests.functional.ui.apps._dc_app_common import (
    TG_ID, VERSION_0, VERSION_1,
    make_mock_tg, make_mock_auth, make_mock_version_svc, make_minimal_term_diff,
    make_default_patches, render_page,
)
import streamlit as st  # noqa: E402

_mock_tg        = make_mock_tg(stale=True)
_mock_auth      = make_mock_auth()
_mock_vsvc      = make_mock_version_svc()
_term_diff      = make_minimal_term_diff()

_stale_diff = MagicMock()
_stale_diff.is_empty = False
_stale_diff.summary_parts.return_value = ["1 new column added"]

st.session_state["auth"] = _mock_auth
st.query_params["table_group_id"] = TG_ID

render_page(make_default_patches(_mock_tg, _term_diff, _mock_vsvc, stale_diff=_stale_diff))
