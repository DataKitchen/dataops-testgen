"""
Streamlit app script for AppTest — snapshot quality rebuild flow.

Simulates a snapshot-backed contract where rebuild_quality_from_suite returns
YAML that includes a newly-added test. Verifies that dc_yaml is populated
with the rebuilt quality section after a fresh page load.
"""
from __future__ import annotations

from tests.functional.ui.apps._dc_app_common import (
    TG_ID, CONTRACT_ID,
    make_mock_tg, make_mock_auth, make_mock_version_svc, make_minimal_term_diff,
    make_default_patches, render_page,
)
import streamlit as st  # noqa: E402

SUITE_ID    = "cccccccc-0000-0000-0000-000000000003"
NEW_RULE_ID = "dddddddd-0000-0000-0000-000000000004"

BASE_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-contract-snap
schema:
  - name: orders
    properties:
      - name: amount
        physicalType: "numeric(10,2)"
quality: []
"""

REBUILT_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-contract-snap
schema:
  - name: orders
    properties:
      - name: amount
        physicalType: "numeric(10,2)"
quality:
  - id: dddddddd-0000-0000-0000-000000000004
    name: Not Null Check
    type: not_null
    element: orders.amount
    mustBeLessOrEqualTo: 0
"""

VERSION_1 = {
    "version": 1,
    "saved_at": None,
    "label": "With snapshot",
    "contract_yaml": BASE_YAML,
    "snapshot_suite_id": SUITE_ID,
}

_mock_tg        = make_mock_tg()
_mock_auth      = make_mock_auth()
_mock_vsvc      = make_mock_version_svc()
_term_diff      = make_minimal_term_diff(saved_count=1, current_count=1, tg_test_passed=1)

st.session_state["auth"] = _mock_auth
st.query_params["contract_id"] = CONTRACT_ID

render_page(make_default_patches(
    _mock_tg, _term_diff, _mock_vsvc,
    current_version=VERSION_1,
    all_versions=[VERSION_1],
    suite_scope={"included": ["suite_snap"], "excluded": [], "total": 1},
    rebuild_quality_side_effect=lambda _base, _suite_id: REBUILT_YAML,
))
