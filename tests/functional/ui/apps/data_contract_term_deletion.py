"""
Streamlit app script for AppTest — Data Contract term deletion flow.

Sets up a rich YAML in session state, optionally applies a deletion payload
(dc_test_delete_payload), then renders the page so tests can inspect
the resulting YAML in session state.

The deletion logic mirrors on_bulk_delete_terms from data_contract.py,
applied directly in the script so it runs before the page render.
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Block custom component registration BEFORE any testgen UI imports.
# ---------------------------------------------------------------------------
import streamlit.components.v1 as _stv1
_stv1.declare_component = MagicMock(return_value=MagicMock())

if "testgen.ui.components.utils.component" not in sys.modules:
    sys.modules["testgen.ui.components.utils.component"] = MagicMock()

_mock_tg_component = MagicMock()
if "testgen.ui.components.widgets.testgen_component" not in sys.modules:
    sys.modules["testgen.ui.components.widgets.testgen_component"] = _mock_tg_component

import streamlit as st  # noqa: E402
import yaml as _yaml  # noqa: E402

# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------
TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"

FULL_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-contract-full
schema:
  - name: orders
    properties:
      - name: amount
        physicalType: "numeric(10,2)"
        required: true
        logicalType: quantity
        description: "Order amount"
        criticalDataElement: true
        customProperties:
          - property: testgen.primaryKey
            value: "false"
          - property: testgen.minimum
            value: "0"
          - property: testgen.maximum
            value: "99999"
          - property: testgen.minLength
            value: "1"
          - property: testgen.maxLength
            value: "10"
          - property: testgen.format
            value: decimal
quality:
  - id: rule-test-001
    type: not_null
    column: amount
    dimension: completeness
  - id: rule-test-002
    type: max_val
    column: amount
    dimension: accuracy
"""

VERSION_1 = {
    "version": 1,
    "saved_at": datetime(2024, 2, 20, 10, 0, 0),
    "label": "Updated",
    "contract_yaml": FULL_YAML,
    "snapshot_suite_id": "cccccccc-0000-0000-0000-000000000003",
}

VERSION_0 = {
    "version": 0,
    "saved_at": datetime(2024, 1, 15, 10, 0, 0),
    "label": "Initial",
    "contract_yaml": FULL_YAML,
    "snapshot_suite_id": "bbbbbbbb-0000-0000-0000-000000000002",
}

# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------
_mock_tg = MagicMock()
_mock_tg.table_groups_name = "Test Orders"
_mock_tg.id = TG_ID
_mock_tg.project_code = "DEFAULT"
_mock_tg.contract_stale = False

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
_minimal_term_diff.tg_monitor_passed = 0
_minimal_term_diff.tg_monitor_failed = 0
_minimal_term_diff.tg_monitor_warning = 0
_minimal_term_diff.tg_monitor_error = 0
_minimal_term_diff.tg_monitor_not_run = 0
_minimal_term_diff.tg_test_passed = 0
_minimal_term_diff.tg_test_failed = 0
_minimal_term_diff.tg_test_warning = 0
_minimal_term_diff.tg_test_error = 0
_minimal_term_diff.tg_test_not_run = 0
_minimal_term_diff.tg_hygiene_definite = 0
_minimal_term_diff.tg_hygiene_likely = 0
_minimal_term_diff.tg_hygiene_possible = 0

# ---------------------------------------------------------------------------
# Session / query params — set before deletion logic and page render
# ---------------------------------------------------------------------------
st.session_state["auth"] = _mock_auth
st.query_params["table_group_id"] = TG_ID

# ---------------------------------------------------------------------------
# Apply deletion payload BEFORE page render (if staged in session state).
# This mirrors the core of on_bulk_delete_terms from data_contract.py.
# ---------------------------------------------------------------------------
yaml_key    = f"dc_yaml:{TG_ID}"
version_key = f"dc_version:{TG_ID}"

# Seed the version record so the page render does NOT reload from DB
# (which would pop yaml_key and overwrite our mutated YAML).
if version_key not in st.session_state:
    st.session_state[version_key] = VERSION_1

# Ensure FULL_YAML is seeded if not already set (first run after test sets it)
if yaml_key not in st.session_state:
    st.session_state[yaml_key] = FULL_YAML

_delete_payload = st.session_state.pop("dc_test_delete_payload", None)

if _delete_payload is not None:
    _current_yaml = st.session_state.get(yaml_key, "")
    _doc = _yaml.safe_load(_current_yaml) or {}
    _terms = _delete_payload.get("terms", [])

    # Quality rule deletion
    _rule_ids = {t["rule_id"] for t in _terms if t.get("rule_id")}
    if _rule_ids:
        _doc["quality"] = [q for q in (_doc.get("quality") or []) if str(q.get("id", "")) not in _rule_ids]

    # Schema field deletion
    _FIELD_MAP: dict[tuple[str, str], str] = {
        ("ddl",        "Data Type"):             "physicalType",
        ("ddl",        "Not Null"):              "required",
        ("ddl",        "Primary Key"):           "_customProperties.testgen.primaryKey",
        ("profiling",  "Min Value"):             "_customProperties.testgen.minimum",
        ("profiling",  "Max Value"):             "_customProperties.testgen.maximum",
        ("profiling",  "Min Length"):            "_customProperties.testgen.minLength",
        ("profiling",  "Max Length"):            "_customProperties.testgen.maxLength",
        ("profiling",  "Format"):                "_customProperties.testgen.format",
        ("profiling",  "Logical Type"):          "logicalType",
        ("governance", "Critical Data Element"): "criticalDataElement",
        ("governance", "Description"):           "description",
    }
    for _schema_entry in (_doc.get("schema") or []):
        _tbl = _schema_entry.get("name", "")
        for _prop in (_schema_entry.get("properties") or []):
            _col = _prop.get("name", "")
            for _t in _terms:
                if _t.get("rule_id"):
                    continue
                if _t.get("table", "") != _tbl or _t.get("col", "") != _col:
                    continue
                _field = _FIELD_MAP.get((_t.get("source", ""), _t.get("name", "")))
                if not _field:
                    continue
                if _field.startswith("_customProperties."):
                    _cp_key = _field[len("_customProperties."):]
                    _existing = _prop.get("customProperties") or []
                    _updated_cp = [c for c in _existing if c.get("property") != _cp_key]
                    if _updated_cp:
                        _prop["customProperties"] = _updated_cp
                    else:
                        _prop.pop("customProperties", None)
                else:
                    _prop.pop(_field, None)

    st.session_state[yaml_key] = _yaml.dump(_doc, default_flow_style=False, allow_unicode=True, sort_keys=False)

# ---------------------------------------------------------------------------
# Render the page with all external dependencies patched out
# ---------------------------------------------------------------------------
_patches = [
    patch("testgen.ui.views.data_contract.TableGroup.get_minimal", return_value=_mock_tg),
    patch("testgen.ui.views.data_contract.TableGroup.get", return_value=_mock_tg),
    patch("testgen.ui.views.data_contract.has_any_version", return_value=True),
    patch("testgen.ui.views.data_contract.load_contract_version", return_value=VERSION_1),
    patch("testgen.ui.views.data_contract.list_contract_versions", return_value=[VERSION_1, VERSION_0]),
    patch("testgen.ui.views.data_contract.compute_staleness_diff", return_value=None),
    patch("testgen.ui.views.data_contract.compute_term_diff", return_value=_minimal_term_diff),
    patch("testgen.ui.views.data_contract._fetch_suite_scope",
          return_value={"included": ["suite_a"], "excluded": [], "total": 1}),
    patch("testgen.ui.views.data_contract._fetch_last_run_dates",
          return_value={"suites": {}, "last_run_date": None}),
    patch("testgen.ui.views.data_contract._fetch_test_statuses", return_value={}),
    patch("testgen.ui.views.data_contract._fetch_anomalies", return_value=[]),
    patch("testgen.ui.views.data_contract._fetch_governance_data", return_value={}),
    patch("testgen.ui.views.data_contract.mark_contract_not_stale", MagicMock()),
    patch("testgen.ui.views.data_contract.sync_import_to_snapshot_suite", MagicMock()),
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
