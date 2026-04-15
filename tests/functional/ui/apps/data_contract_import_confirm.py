"""
Streamlit app script for AppTest — Data Contract import confirmation dialog.

Directly invokes _confirm_import_dialog with a pre-built ContractDiff so the
dialog renders immediately. Test scenario is chosen via session state:

  dc_test_confirm_scenario: str  (default: "creates")

Scenarios
---------
  creates     — 3 creates, 2 updates, 1 no_change, 2 skipped, no warnings
  errors      — preview.has_errors is True (table group not found)
  governance  — governance_updates + contract_updates (no quality rules)
  warnings    — 1 create + 1 skipped rule with a warning string
  orphans     — orphaned_ids present but no creates/updates
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import streamlit.components.v1 as _stv1
_stv1.declare_component = MagicMock(return_value=MagicMock())

if "testgen.ui.components.utils.component" not in sys.modules:
    sys.modules["testgen.ui.components.utils.component"] = MagicMock()

_mock_tg_component = MagicMock()
if "testgen.ui.components.widgets.testgen_component" not in sys.modules:
    sys.modules["testgen.ui.components.widgets.testgen_component"] = _mock_tg_component

import streamlit as st  # noqa: E402

TG_ID      = "aaaaaaaa-0000-0000-0000-000000000001"
SNAP_ID    = "bbbbbbbb-0000-0000-0000-000000000002"
IMPORT_KEY = f"dc_import_result:{TG_ID}"
SAMPLE_YAML = "apiVersion: v3.1.0\nkind: DataContract\nid: test\nschema: []\nquality: []\n"

_mock_auth = MagicMock()
_mock_auth.is_logged_in = True
_mock_auth.user_has_permission.return_value = True

_mock_version = MagicMock()
_mock_version.current = "5.0.0"
_mock_version.latest = "5.0.0"

st.session_state["auth"] = _mock_auth

# ---------------------------------------------------------------------------
# Build preview diff for selected scenario
# ---------------------------------------------------------------------------
from testgen.commands.odcs_contract import ContractDiff  # noqa: E402

_scenario = st.session_state.pop("dc_test_confirm_scenario", "creates")

if _scenario == "creates":
    _preview = ContractDiff(
        test_inserts=[{"test_type": "Missing_Pct"}, {"test_type": "Unique_Pct"}, {"test_type": "Min_Val"}],
        test_updates=[{"id": "u1", "threshold_value": "10"}, {"id": "u2", "threshold_value": "5"}],
        no_change_rules=1,
        skipped_rules=2,
    )
elif _scenario == "errors":
    _preview = ContractDiff(errors=["Table group 'aaaaaaaa-0000-0000-0000-000000000001' not found."])
elif _scenario == "governance":
    _preview = ContractDiff(
        governance_updates=[
            {"table": "orders", "col": "amount", "updates": {"description": "Total amount"}},
            {"table": "orders", "col": "status", "updates": {"critical_data_element": True}},
        ],
        contract_updates={"contract_version": "2.0.0", "contract_status": "published"},
    )
elif _scenario == "warnings":
    _preview = ContractDiff(
        test_inserts=[{"test_type": "Missing_Pct"}],
        skipped_rules=1,
        warnings=["Quality rule id 'bad-uuid' not found in table group — may have been deleted. Skipped."],
    )
elif _scenario == "orphans":
    _preview = ContractDiff(
        orphaned_ids=["uuid-orphan-1", "uuid-orphan-2"],
        warnings=[
            "Test 'uuid-orphan-1' (type: Missing_Pct) is in the table group but not in YAML — not deleted.",
            "Test 'uuid-orphan-2' (type: Unique_Pct) is in the table group but not in YAML — not deleted.",
        ],
    )
else:
    _preview = ContractDiff()

# ---------------------------------------------------------------------------
# Mock successful import diff for Confirm button
# ---------------------------------------------------------------------------
_applied_diff = ContractDiff(
    test_inserts=_preview.test_inserts,
    test_updates=_preview.test_updates,
)

_patches = [
    patch("testgen.ui.views.dialogs.data_contract_dialogs.run_import_contract",
          return_value=_applied_diff),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.sync_import_to_snapshot_suite", MagicMock()),
    patch("testgen.ui.views.dialogs.data_contract_dialogs._clear_contract_cache", MagicMock()),
    patch("testgen.ui.views.dialogs.data_contract_dialogs.safe_rerun",
          MagicMock(side_effect=st.rerun)),
    patch("testgen.common.version_service.get_version", return_value=_mock_version),
]

with ExitStack() as _stack:
    for _p in _patches:
        _stack.enter_context(_p)

    from testgen.ui.views.dialogs.data_contract_dialogs import _confirm_import_dialog  # noqa: E402

    _confirm_import_dialog(_preview, SAMPLE_YAML, TG_ID, SNAP_ID, IMPORT_KEY)
