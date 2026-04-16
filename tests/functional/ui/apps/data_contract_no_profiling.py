"""
Streamlit app script for AppTest — Data Contract first-time flow with missing profiling.

Identical to data_contract_first_time_flow.py except has_profiling=False in prereqs.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import streamlit.components.v1 as _stv1
_stv1.declare_component = MagicMock(return_value=MagicMock())

if "testgen.ui.components.utils.component" not in sys.modules:
    sys.modules["testgen.ui.components.utils.component"] = MagicMock()

_mock_tg_component = MagicMock()
if "testgen.ui.components.widgets.testgen_component" not in sys.modules:
    sys.modules["testgen.ui.components.widgets.testgen_component"] = _mock_tg_component

import streamlit as st  # noqa: E402

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
CONTRACT_ID = "cccccccc-0000-0000-0000-000000000001"

SAMPLE_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-contract-001
schema:
  - name: orders
    properties:
      - name: id
        physicalType: integer
quality: []
"""

_mock_tg = MagicMock()
_mock_tg.table_groups_name = "Test Orders"
_mock_tg.id = TG_ID

_mock_auth = MagicMock()
_mock_auth.is_logged_in = True
_mock_auth.user_has_permission.return_value = True

_mock_version = MagicMock()
_mock_version.current = "5.0.0"
_mock_version.latest = "5.0.0"

def _mock_capture_yaml(tg_id: str, buf) -> None:  # noqa: ANN001
    buf.write(SAMPLE_YAML)

st.session_state["auth"] = _mock_auth
st.query_params["contract_id"] = CONTRACT_ID

with (
    patch("testgen.ui.views.data_contract.get_contract", return_value={
        "contract_id": CONTRACT_ID, "table_group_id": TG_ID,
        "project_code": "DEFAULT", "is_active": True, "name": "Test Contract",
    }),
    patch("testgen.ui.views.data_contract.TableGroup.get_minimal", return_value=_mock_tg),
    patch("testgen.ui.views.data_contract.has_any_version", return_value=False),
    patch("testgen.ui.views.data_contract._check_contract_prerequisites", return_value={
        "has_profiling": False,   # <-- no profiling run
        "last_profiling": None,
        "has_suites": True,
        "suite_ct": 3,
        "meta_pct": 60,
    }),
    patch("testgen.ui.queries.data_contract_queries._capture_yaml", _mock_capture_yaml),
    patch("testgen.ui.views.data_contract._fetch_test_statuses", return_value={}),
    patch("testgen.ui.views.data_contract._fetch_anomalies", return_value=[]),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.TableGroup.get_minimal", return_value=_mock_tg),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.save_contract_version", return_value=0),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.create_contract_snapshot_suite",
          return_value="new-suite-id"),
    patch("testgen.ui.views.dialogs.data_contract_dialogs._persist_pending_edits", MagicMock()),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.safe_rerun",
          MagicMock(side_effect=st.rerun)),
    patch("testgen.ui.components.widgets.page.testgen_component",
          _mock_tg_component.testgen_component),
    patch("testgen.common.version_service.get_version", return_value=_mock_version),
    patch("testgen.ui.components.widgets.page.version_service",
          MagicMock(get_version=lambda: _mock_version)),
):
    from testgen.ui.views.data_contract import DataContractPage  # noqa: E402

    _page = DataContractPage.__new__(DataContractPage)
    _page.router = MagicMock()
    _page.render(contract_id=CONTRACT_ID)
