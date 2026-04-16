"""
Streamlit app script for AppTest — Data Contract with pre-seeded pending edits.

Like saved_version but with pending edits injectable via dc_test_inject_pending
in session state. Tests verify round-trip through dc_pending:{TG_ID}.
"""
from __future__ import annotations

from tests.functional.ui.apps._dc_app_common import (
    TG_ID, CONTRACT_ID, VERSION_0, VERSION_1, SAMPLE_YAML,
    make_mock_tg, make_mock_auth, make_mock_version_svc, make_minimal_term_diff,
    make_default_patches, render_page,
)
import streamlit as st  # noqa: E402

pending_key = f"dc_pending:{CONTRACT_ID}"
yaml_key    = f"dc_yaml:{CONTRACT_ID}"
version_key = f"dc_version:{CONTRACT_ID}"

# Inject pre-seeded pending edits when provided via test side-channel
_inject_pending = st.session_state.pop("dc_test_inject_pending", None)
if _inject_pending is not None:
    st.session_state[pending_key] = _inject_pending

# Seed yaml + version so page uses cached values (no DB round-trip)
if yaml_key not in st.session_state:
    st.session_state[yaml_key] = SAMPLE_YAML
if version_key not in st.session_state:
    st.session_state[version_key] = VERSION_1

_mock_tg        = make_mock_tg()
_mock_auth      = make_mock_auth()
_mock_vsvc      = make_mock_version_svc()
_term_diff      = make_minimal_term_diff()

st.session_state["auth"] = _mock_auth
st.query_params["contract_id"] = CONTRACT_ID

render_page(make_default_patches(_mock_tg, _term_diff, _mock_vsvc))
