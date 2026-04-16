"""
Streamlit app script for AppTest — Data Contract historical (older) version view.

Like saved_version but:
- query param version=0 requests VERSION_0 (the older version)
- load_contract_version returns VERSION_0 → is_latest = False
- Read-only banners shown; Save/Regenerate buttons hidden
"""
from __future__ import annotations

from tests.functional.ui.apps._dc_app_common import (
    TG_ID, CONTRACT_ID, VERSION_0, VERSION_1,
    make_mock_tg, make_mock_auth, make_mock_version_svc, make_minimal_term_diff,
    make_default_patches, render_page,
)
import streamlit as st  # noqa: E402

_mock_tg        = make_mock_tg()
_mock_auth      = make_mock_auth()
_mock_vsvc      = make_mock_version_svc()
_term_diff      = make_minimal_term_diff()

st.session_state["auth"] = _mock_auth
st.query_params["contract_id"] = CONTRACT_ID
st.query_params["version"] = "0"  # request VERSION_0 (historical)

render_page(make_default_patches(
    _mock_tg, _term_diff, _mock_vsvc,
    current_version=VERSION_0,
))
