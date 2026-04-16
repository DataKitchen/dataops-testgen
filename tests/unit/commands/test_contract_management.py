# tests/unit/commands/test_contract_management.py
"""Unit tests for contract_management.py — pytest -m unit"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

pytestmark = pytest.mark.unit

CONTRACT_ID = "cccccccc-0000-0000-0000-000000000001"
SUITE_ID    = "ssssssss-0000-0000-0000-000000000002"
TG_ID       = "aaaaaaaa-0000-0000-0000-000000000003"


@pytest.fixture(autouse=True)
def patch_session(monkeypatch):
    monkeypatch.setattr("testgen.commands.contract_management.with_database_session", lambda f: f)
    monkeypatch.setattr("testgen.commands.contract_management.get_tg_schema", lambda: "tg")
    monkeypatch.setattr("testgen.commands.contract_management.get_current_session", MagicMock())


class Test_GetContract:
    def test_returns_dict_when_found(self):
        from testgen.commands.contract_management import get_contract
        with patch("testgen.commands.contract_management.fetch_dict_from_db",
                   return_value=[{"contract_id": CONTRACT_ID, "table_group_id": TG_ID,
                                  "project_code": "P1", "is_active": True,
                                  "test_suite_id": SUITE_ID, "name": "my_contract"}]):
            result = get_contract(CONTRACT_ID)
        assert result["contract_id"] == CONTRACT_ID
        assert result["project_code"] == "P1"

    def test_returns_none_when_not_found(self):
        from testgen.commands.contract_management import get_contract
        with patch("testgen.commands.contract_management.fetch_dict_from_db", return_value=[]):
            assert get_contract(CONTRACT_ID) is None


class Test_CreateContract:
    def test_returns_ids_on_success(self):
        from testgen.commands.contract_management import create_contract
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: CONTRACT_ID if k == "contract_id" else SUITE_ID
        mock_session.execute.return_value.mappings.return_value.first.return_value = mock_row
        with patch("testgen.commands.contract_management.get_current_session", return_value=mock_session):
            result = create_contract("my_contract", "P1", TG_ID)
        assert result["contract_id"] == CONTRACT_ID
        assert result["test_suite_id"] == SUITE_ID

    def test_raises_on_missing_row(self):
        from testgen.commands.contract_management import create_contract
        mock_session = MagicMock()
        mock_session.execute.return_value.mappings.return_value.first.return_value = None
        with patch("testgen.commands.contract_management.get_current_session", return_value=mock_session):
            with pytest.raises(ValueError, match="Failed to create contract"):
                create_contract("my_contract", "P1", TG_ID)


class Test_DeleteContract:
    def test_executes_delete_queries(self):
        from testgen.commands.contract_management import delete_contract
        with patch("testgen.commands.contract_management.execute_db_queries") as mock_exec:
            mock_exec.return_value = ([None, None, None], [1, 2, 1])
            delete_contract(CONTRACT_ID, SUITE_ID, ["snap1", "snap2"])
        assert mock_exec.called


class Test_SetContractActive:
    def test_sets_active_true(self):
        from testgen.commands.contract_management import set_contract_active
        with patch("testgen.commands.contract_management.execute_db_queries") as mock_exec:
            mock_exec.return_value = ([None], [1])
            set_contract_active(CONTRACT_ID, True)
        call_sql = mock_exec.call_args[0][0][0][0]
        assert "is_active" in call_sql
        assert ":active" in call_sql

    def test_sets_active_false(self):
        from testgen.commands.contract_management import set_contract_active
        with patch("testgen.commands.contract_management.execute_db_queries") as mock_exec:
            mock_exec.return_value = ([None], [1])
            set_contract_active(CONTRACT_ID, False)
        assert mock_exec.called
