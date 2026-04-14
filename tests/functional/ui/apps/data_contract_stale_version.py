"""
Streamlit app script for AppTest — Data Contract stale-version flow.

Identical to data_contract_saved_version.py except:
- TableGroup.contract_stale = True
- compute_staleness_diff returns a non-empty StaleDiff (triggers warning banner)
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from datetime import datetime
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

SAMPLE_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-contract-001
schema:
  - name: orders
    properties:
      - name: id
        physicalType: integer
        required: true
quality: []
"""

VERSION_0 = {
    "version": 0,
    "saved_at": datetime(2024, 1, 15, 10, 0, 0),
    "label": "Initial",
    "contract_yaml": SAMPLE_YAML,
    "snapshot_suite_id": "bbbbbbbb-0000-0000-0000-000000000002",
}

VERSION_1 = {
    "version": 1,
    "saved_at": datetime(2024, 2, 20, 10, 0, 0),
    "label": "Updated",
    "contract_yaml": SAMPLE_YAML,
    "snapshot_suite_id": "cccccccc-0000-0000-0000-000000000003",
}

_mock_tg = MagicMock()
_mock_tg.table_groups_name = "Test Orders"
_mock_tg.id = TG_ID
_mock_tg.project_code = "DEFAULT"
_mock_tg.contract_stale = True  # <-- stale

_mock_auth = MagicMock()
_mock_auth.is_logged_in = True
_mock_auth.user_has_permission.return_value = True

_mock_version_svc = MagicMock()
_mock_version_svc.current = "5.0.0"
_mock_version_svc.latest = "5.0.0"

_minimal_term_diff = MagicMock()
_minimal_term_diff.entries = []
_minimal_term_diff.saved_count = 2
_minimal_term_diff.current_count = 2
for _attr in ("tg_monitor_passed", "tg_monitor_failed", "tg_monitor_warning",
              "tg_monitor_error", "tg_monitor_not_run", "tg_test_passed",
              "tg_test_failed", "tg_test_warning", "tg_test_error", "tg_test_not_run",
              "tg_hygiene_definite", "tg_hygiene_likely", "tg_hygiene_possible"):
    setattr(_minimal_term_diff, _attr, 0)

# Non-empty StaleDiff — enough to pass is_empty == False and provide summary_parts()
_stale_diff = MagicMock()
_stale_diff.is_empty = False
_stale_diff.summary_parts.return_value = ["1 new column added"]

st.session_state["auth"] = _mock_auth
st.query_params["table_group_id"] = TG_ID

_patches = [
    patch("testgen.ui.views.data_contract.TableGroup.get_minimal", return_value=_mock_tg),
    patch("testgen.ui.views.data_contract.TableGroup.get", return_value=_mock_tg),
    patch("testgen.ui.views.data_contract.has_any_version", return_value=True),
    patch("testgen.ui.views.data_contract.load_contract_version", return_value=VERSION_1),
    patch("testgen.ui.views.data_contract.list_contract_versions", return_value=[VERSION_1, VERSION_0]),
    patch("testgen.ui.views.data_contract.compute_staleness_diff", return_value=_stale_diff),
    patch("testgen.ui.views.data_contract.compute_term_diff", return_value=_minimal_term_diff),
    patch("testgen.ui.views.data_contract._fetch_suite_scope",
          return_value={"included": ["suite_a"], "excluded": [], "total": 1}),
    patch("testgen.ui.views.data_contract._fetch_last_run_dates",
          return_value={"suites": {}, "last_run_date": None}),
    patch("testgen.ui.views.data_contract._fetch_test_statuses", return_value={}),
    patch("testgen.ui.views.data_contract._fetch_anomalies", return_value=[]),
    patch("testgen.ui.views.data_contract._fetch_governance_data", return_value={}),
    patch("testgen.ui.views.data_contract._get_snapshot_test_count", return_value=0),
    patch("testgen.ui.views.data_contract.mark_contract_not_stale", MagicMock()),
    patch("testgen.commands.export_data_contract.rebuild_quality_from_suite",
          side_effect=lambda base_yaml, _suite_id: base_yaml),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.TableGroup.get_minimal", return_value=_mock_tg),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.save_contract_version", return_value=2),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.create_contract_snapshot_suite",
          return_value="new-suite-id"),
    patch("testgen.ui.views.dialogs.data_contract_dialogs._persist_pending_edits", MagicMock()),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.safe_rerun",
          MagicMock(side_effect=st.rerun)),
    patch("testgen.ui.views.data_contract.safe_rerun", MagicMock(side_effect=st.rerun)),
    patch("testgen.ui.components.widgets.page.testgen_component",
          _mock_tg_component.testgen_component),
    patch("testgen.common.version_service.get_version", return_value=_mock_version_svc),
    patch("testgen.ui.components.widgets.page.version_service",
          MagicMock(get_version=lambda: _mock_version_svc)),
]

with ExitStack() as _stack:
    for _p in _patches:
        _stack.enter_context(_p)

    from testgen.ui.views.data_contract import DataContractPage  # noqa: E402

    _page = DataContractPage.__new__(DataContractPage)
    _page.router = MagicMock()
    _page.render(table_group_id=TG_ID)
