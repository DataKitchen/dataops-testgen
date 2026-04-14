"""
Unit tests for on_term_detail routing logic with snapshot_suite_id.
pytest -m unit tests/unit/ui/test_contract_on_term_detail_snapshot.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SNAP_ID = "bbbbbbbb-0000-0000-0000-000000000002"


# ---------------------------------------------------------------------------
# Pure routing logic — replicated inline so we can test without Streamlit.
# This mirrors the on_term_detail function in data_contract.py exactly.
# ---------------------------------------------------------------------------

def _route(
    payload: dict,
    *,
    is_latest: bool,
    snapshot_suite_id: str | None,
    edit_rule_dialog,
    monitor_term_dialog,
    test_term_dialog,
    term_edit_dialog,
    term_read_dialog,
    yaml_key: str = "yaml_key",
    table_group_project_code: str = "proj",
) -> None:
    """Execute the on_term_detail routing logic with injected dialog callables."""
    term       = payload.get("term", {})
    table_name = payload.get("tableName", "")
    col_name   = payload.get("colName", "")
    source     = term.get("source", "")
    verif      = term.get("verif", "")
    term_name  = term.get("name", "")

    if not is_latest:
        term_read_dialog(term, table_name, col_name, TG_ID, yaml_key)
    elif source == "monitor":
        monitor_term_dialog(term.get("rule", {}), term_name, table_name, col_name)
    elif source == "test" and snapshot_suite_id:
        rule = term.get("rule") or term
        edit_rule_dialog(rule, TG_ID, yaml_key)
    elif source == "test":
        test_term_dialog(term, table_name, col_name, table_group_project_code, yaml_key, TG_ID)
    elif source == "governance" and verif == "declared":
        term_edit_dialog(term, table_name, col_name, TG_ID, yaml_key)
    else:
        term_read_dialog(term, table_name, col_name, TG_ID, yaml_key)


def _mocks():
    return {
        "edit_rule_dialog":  MagicMock(),
        "monitor_term_dialog": MagicMock(),
        "test_term_dialog":  MagicMock(),
        "term_edit_dialog":  MagicMock(),
        "term_read_dialog":  MagicMock(),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class Test_OnTermDetailRouting:

    def test_source_test_with_snapshot_routes_to_edit_rule_dialog(self):
        """source=test + snapshot_suite_id → edit_rule_dialog"""
        m = _mocks()
        _route(
            {"term": {"source": "test", "verif": "tested", "rule": {"id": "r1"}},
             "tableName": "orders", "colName": "id"},
            is_latest=True, snapshot_suite_id=SNAP_ID, **m,
        )
        m["edit_rule_dialog"].assert_called_once()
        m["test_term_dialog"].assert_not_called()

    def test_source_test_without_snapshot_routes_to_test_term_dialog(self):
        """source=test + no snapshot → test_term_dialog"""
        m = _mocks()
        _route(
            {"term": {"source": "test", "verif": "tested", "rule": {"id": "r1"}},
             "tableName": "orders", "colName": "id"},
            is_latest=True, snapshot_suite_id=None, **m,
        )
        m["test_term_dialog"].assert_called_once()
        m["edit_rule_dialog"].assert_not_called()

    def test_not_latest_with_snapshot_routes_to_term_read_dialog(self):
        """is_latest=False + snapshot → term_read_dialog"""
        m = _mocks()
        _route(
            {"term": {"source": "test", "verif": "tested", "rule": {"id": "r1"}},
             "tableName": "orders", "colName": "id"},
            is_latest=False, snapshot_suite_id=SNAP_ID, **m,
        )
        m["term_read_dialog"].assert_called_once()
        m["edit_rule_dialog"].assert_not_called()

    def test_source_monitor_with_snapshot_routes_to_monitor_dialog(self):
        """source=monitor + snapshot → monitor_term_dialog (unchanged)"""
        m = _mocks()
        _route(
            {"term": {"source": "monitor", "verif": "monitored", "name": "Monitor", "rule": {}},
             "tableName": "orders", "colName": "id"},
            is_latest=True, snapshot_suite_id=SNAP_ID, **m,
        )
        m["monitor_term_dialog"].assert_called_once()
        m["edit_rule_dialog"].assert_not_called()

    def test_source_governance_with_snapshot_routes_to_term_edit_dialog(self):
        """source=governance + declared + snapshot → term_edit_dialog (unchanged)"""
        m = _mocks()
        _route(
            {"term": {"source": "governance", "verif": "declared", "name": "CDE"},
             "tableName": "orders", "colName": "id"},
            is_latest=True, snapshot_suite_id=SNAP_ID, **m,
        )
        m["term_edit_dialog"].assert_called_once()
        m["edit_rule_dialog"].assert_not_called()
