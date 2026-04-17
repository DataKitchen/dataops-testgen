"""
Tests for the refactored contract_versions.py (contract_id-based, contract_versions table).
pytest -m unit tests/unit/commands/test_contract_versions_refactor.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import pytest

pytestmark = pytest.mark.unit

CONTRACT_ID = "cccccccc-0000-0000-0000-000000000001"
TG_ID       = "aaaaaaaa-0000-0000-0000-000000000003"


@pytest.fixture(autouse=True)
def patch_session(monkeypatch):
    monkeypatch.setattr("testgen.commands.contract_versions.with_database_session", lambda f: f)
    monkeypatch.setattr("testgen.commands.contract_versions.get_tg_schema", lambda: "tg")


class Test_HasAnyVersion:
    def test_true_when_rows(self):
        from testgen.commands.contract_versions import has_any_version
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[{"1": 1}]):
            assert has_any_version(CONTRACT_ID) is True

    def test_false_when_empty(self):
        from testgen.commands.contract_versions import has_any_version
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[]):
            assert has_any_version(CONTRACT_ID) is False

    def test_queries_contract_versions_table(self):
        from testgen.commands.contract_versions import has_any_version
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[]) as mock_fetch:
            has_any_version(CONTRACT_ID)
        sql = mock_fetch.call_args[0][0]
        assert "contract_versions" in sql
        assert "contract_id" in sql


class Test_LoadContractVersion:
    _SAVED_AT = datetime(2026, 3, 1, tzinfo=timezone.utc)

    def test_returns_none_when_not_found(self):
        from testgen.commands.contract_versions import load_contract_version
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[]):
            assert load_contract_version(CONTRACT_ID) is None

    def test_returns_dict_on_found(self):
        from testgen.commands.contract_versions import load_contract_version
        row = {"version": 2, "saved_at": self._SAVED_AT, "label": "v2",
               "contract_yaml": "yaml", "snapshot_suite_id": None, "is_current": True}
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[row]):
            result = load_contract_version(CONTRACT_ID)
        assert result["version"] == 2

    def test_loads_latest_when_version_none(self):
        from testgen.commands.contract_versions import load_contract_version
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[]) as mock_f:
            load_contract_version(CONTRACT_ID)
        sql = mock_f.call_args[0][0]
        assert "is_current" in sql or "ORDER BY" in sql

    def test_loads_specific_version(self):
        from testgen.commands.contract_versions import load_contract_version
        row = {"version": 1, "saved_at": self._SAVED_AT, "label": None,
               "contract_yaml": "yaml", "snapshot_suite_id": None, "is_current": False}
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[row]) as mock_f:
            load_contract_version(CONTRACT_ID, version=1)
        sql = mock_f.call_args[0][0]
        assert ":ver" in sql


class Test_SaveContractVersion:
    def test_returns_new_version_number(self):
        from testgen.commands.contract_versions import save_contract_version
        # Single combined CTE query: return_values[0] is the new version number
        with patch("testgen.commands.contract_versions.execute_db_queries",
                   return_value=([3], [1])):
            v = save_contract_version(CONTRACT_ID, TG_ID, "yaml:", term_count=5)
        assert v == 3

    def test_sql_touches_contract_versions_table(self):
        from testgen.commands.contract_versions import save_contract_version
        with patch("testgen.commands.contract_versions.execute_db_queries",
                   return_value=([0], [1])) as mock_exec:
            save_contract_version(CONTRACT_ID, TG_ID, "yaml:", term_count=0)
        # Single combined CTE query (index 0) must reference contract_versions
        sql = mock_exec.call_args[0][0][0][0]
        assert "contract_versions" in sql
