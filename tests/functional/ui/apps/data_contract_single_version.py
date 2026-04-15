"""
Streamlit app script for AppTest — Data Contract single-version flow.

Like saved_version but with only ONE version.
Used to test:
- "Delete contract" button disabled with 1 version
- No version-picker selectbox with 1 version
"""
from __future__ import annotations

from tests.functional.ui.apps._dc_app_common import (
    TG_ID, VERSION_0,
    make_mock_tg, make_mock_auth, make_mock_version_svc, make_minimal_term_diff,
    make_default_patches, render_page,
)
import streamlit as st  # noqa: E402

_mock_tg        = make_mock_tg()
_mock_auth      = make_mock_auth()
_mock_vsvc      = make_mock_version_svc()
_term_diff      = make_minimal_term_diff(saved_count=1, current_count=1)

st.session_state["auth"] = _mock_auth
st.query_params["table_group_id"] = TG_ID

render_page(make_default_patches(
    _mock_tg, _term_diff, _mock_vsvc,
    current_version=VERSION_0,
    all_versions=[VERSION_0],
))
