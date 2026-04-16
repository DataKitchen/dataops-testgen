"""
Shared boilerplate for data-contract AppTest fixture scripts.

Import this module FIRST — it patches streamlit internals before any testgen
UI code is loaded, and exports factory functions used by all fixture scripts.
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import MagicMock, patch

# ── Must happen before any testgen component imports ──────────────────────────
import streamlit.components.v1 as _stv1
_stv1.declare_component = MagicMock(return_value=MagicMock())

if "testgen.ui.components.utils.component" not in sys.modules:
    sys.modules["testgen.ui.components.utils.component"] = MagicMock()

mock_tg_component = MagicMock()
if "testgen.ui.components.widgets.testgen_component" not in sys.modules:
    sys.modules["testgen.ui.components.widgets.testgen_component"] = mock_tg_component

import streamlit as st  # noqa: E402

# ── Shared constants ──────────────────────────────────────────────────────────
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
        required: true
      - name: amount
        physicalType: "numeric(10,2)"
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

# ── Mock factories ────────────────────────────────────────────────────────────

def make_mock_tg(stale: bool = False) -> MagicMock:
    m = MagicMock()
    m.table_groups_name = "Test Orders"
    m.id = TG_ID
    m.project_code = "DEFAULT"
    m.contract_stale = stale
    return m


def make_mock_auth() -> MagicMock:
    m = MagicMock()
    m.is_logged_in = True
    m.user_has_permission.return_value = True
    return m


def make_mock_version_svc() -> MagicMock:
    m = MagicMock()
    m.current = "5.0.0"
    m.latest = "5.0.0"
    return m


def make_minimal_term_diff(**overrides: object) -> MagicMock:
    """Create a minimal TermDiffResult mock with all counts defaulting to 0."""
    m = MagicMock()
    m.entries = []
    m.saved_count = overrides.pop("saved_count", 2)
    m.current_count = overrides.pop("current_count", 2)
    for attr in (
        "tg_monitor_passed", "tg_monitor_failed", "tg_monitor_warning",
        "tg_monitor_error", "tg_monitor_not_run", "tg_test_passed",
        "tg_test_failed", "tg_test_warning", "tg_test_error", "tg_test_not_run",
        "tg_hygiene_definite", "tg_hygiene_likely", "tg_hygiene_possible",
    ):
        setattr(m, attr, overrides.pop(attr, 0))
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


def make_default_patches(
    mock_tg: MagicMock,
    minimal_term_diff: MagicMock,
    mock_version_svc: MagicMock,
    *,
    current_version: dict = VERSION_1,
    all_versions: list[dict] | None = None,
    stale_diff: object = None,
    suite_scope: dict | None = None,
    rebuild_quality_side_effect: object = None,
) -> list:
    """Return the standard patch list used by most data-contract fixture scripts."""
    if all_versions is None:
        all_versions = [VERSION_1, VERSION_0]
    if suite_scope is None:
        suite_scope = {"included": ["suite_a"], "excluded": [], "total": 1}
    if rebuild_quality_side_effect is None:
        rebuild_quality_side_effect = lambda base_yaml, _suite_id: base_yaml  # noqa: E731

    return [
        patch("testgen.ui.views.data_contract.get_contract", return_value={
            "contract_id": CONTRACT_ID,
            "table_group_id": TG_ID,
            "project_code": "DEFAULT",
            "is_active": True,
            "name": "Test Contract",
            "test_suite_id": "dddddddd-0000-0000-0000-000000000005",
        }),
        patch("testgen.ui.views.data_contract._render_contract_testing_tab", MagicMock()),
        patch("testgen.ui.views.data_contract.TableGroup.get_minimal", return_value=mock_tg),
        patch("testgen.ui.views.data_contract.TableGroup.get", return_value=mock_tg),
        patch("testgen.ui.views.data_contract.has_any_version", return_value=True),
        patch("testgen.ui.views.data_contract.load_contract_version", return_value=current_version),
        patch("testgen.ui.views.data_contract.list_contract_versions", return_value=all_versions),
        patch("testgen.ui.views.data_contract.compute_staleness_diff", return_value=stale_diff),
        patch("testgen.ui.views.data_contract.compute_term_diff", return_value=minimal_term_diff),
        patch("testgen.ui.views.data_contract._fetch_suite_scope", return_value=suite_scope),
        patch("testgen.ui.views.data_contract._fetch_last_run_dates",
              return_value={"suites": {}, "last_run_date": None}),
        patch("testgen.ui.views.data_contract._fetch_test_statuses", return_value={}),
        patch("testgen.ui.views.data_contract._fetch_anomalies", return_value=[]),
        patch("testgen.ui.views.data_contract._fetch_governance_data", return_value={}),
        patch("testgen.ui.views.data_contract.mark_contract_not_stale", MagicMock()),
        patch("testgen.ui.views.data_contract._count_snapshot_tests", return_value=2),
        patch("testgen.commands.export_data_contract.rebuild_quality_from_suite",
              side_effect=rebuild_quality_side_effect),
        patch("testgen.ui.views.dialogs.data_contract_dialogs.TableGroup.get_minimal", return_value=mock_tg),
        patch("testgen.ui.views.dialogs.data_contract_dialogs.save_contract_version", return_value=2),
        patch("testgen.ui.views.dialogs.data_contract_dialogs.create_contract_snapshot_suite",
              return_value="new-suite-id"),
        patch("testgen.ui.views.dialogs.data_contract_dialogs._persist_pending_edits", MagicMock()),
        patch("testgen.ui.views.dialogs.data_contract_dialogs.safe_rerun",
              MagicMock(side_effect=st.rerun)),
        patch("testgen.ui.views.data_contract.safe_rerun", MagicMock(side_effect=st.rerun)),
        patch("testgen.ui.components.widgets.page.testgen_component",
              mock_tg_component.testgen_component),
        patch("testgen.common.version_service.get_version", return_value=mock_version_svc),
        patch("testgen.ui.components.widgets.page.version_service",
              MagicMock(get_version=lambda: mock_version_svc)),
    ]


def render_page(patches: list, contract_id: str = CONTRACT_ID) -> None:
    """Apply patches and render the DataContractPage."""
    from testgen.ui.views.data_contract import DataContractPage  # noqa: E402

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        page = DataContractPage.__new__(DataContractPage)
        page.router = MagicMock()
        page.render(contract_id=contract_id)
