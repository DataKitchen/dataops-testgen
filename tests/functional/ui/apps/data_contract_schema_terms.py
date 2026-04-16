"""
Streamlit app script for AppTest — Data Contract with schema user_schema_fields.

Simulates a saved contract where orders.amount has user-defined schema fields
(tags, title, unique). Used by Test_SchemaPendingEdits to verify that schema
pending edits increment the pending count and trigger the unsaved-changes banner.
"""
from __future__ import annotations

from tests.functional.ui.apps._dc_app_common import (
    TG_ID, CONTRACT_ID, VERSION_0, VERSION_1,
    make_mock_tg, make_mock_auth, make_mock_version_svc, make_minimal_term_diff,
    make_default_patches, render_page,
)
import streamlit as st  # noqa: E402

SCHEMA_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-contract-002
schema:
  - name: orders
    properties:
      - name: amount
        physicalType: "numeric(10,2)"
        tags:
          - billing
          - finance
        title: Invoice Amount
        unique: false
quality: []
x-testgen:
  user_schema_fields:
    orders.amount:
      - tags
      - title
      - unique
"""

SCHEMA_VERSION_1 = {
    **VERSION_1,
    "contract_yaml": SCHEMA_YAML,
}

pending_key = f"dc_pending:{CONTRACT_ID}"
yaml_key    = f"dc_yaml:{CONTRACT_ID}"
version_key = f"dc_version:{CONTRACT_ID}"

# Seed yaml + version so page uses cached values (no DB round-trip)
if yaml_key not in st.session_state:
    st.session_state[yaml_key] = SCHEMA_YAML
if version_key not in st.session_state:
    st.session_state[version_key] = SCHEMA_VERSION_1

_mock_tg   = make_mock_tg()
_mock_auth = make_mock_auth()
_mock_vsvc = make_mock_version_svc()
_term_diff = make_minimal_term_diff()

st.session_state["auth"] = _mock_auth
st.query_params["contract_id"] = CONTRACT_ID

render_page(
    make_default_patches(
        _mock_tg, _term_diff, _mock_vsvc,
        current_version=SCHEMA_VERSION_1,
    )
)
