"""
Unit tests for delete_contract_version.
pytest -m unit tests/unit/commands/test_delete_contract_version.py
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SNAP_ID = "bbbbbbbb-0000-0000-0000-000000000002"


@pytest.fixture(autouse=True)
def patch_session(monkeypatch):
    monkeypatch.setattr(
        "testgen.commands.contract_snapshot_suite.with_database_session",
        lambda f: f,
    )
    monkeypatch.setattr(
        "testgen.commands.contract_snapshot_suite.get_tg_schema",
        lambda: "tg",
    )


class Test_DeleteContractVersion:

    def test_raises_value_error_when_only_one_version(self):
        """Must raise ValueError when only one version exists."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 1}],  # version count
                   ]):
            with pytest.raises(ValueError, match="Cannot delete the only saved version"):
                delete_contract_version(TG_ID, 0)

    def test_five_delete_statements_when_snapshot_suite_present(self):
        """With snapshot_suite_id: test_results + test_runs + test_definitions + test_suites + contract = 5 total."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 3}],                                    # version count
                       [{"snapshot_suite_id": SNAP_ID}],               # snapshot suite id
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(TG_ID, 1)

        assert mock_exec.call_count == 1
        calls = mock_exec.call_args[0][0]
        assert len(calls) == 5
        sql_statements = [c[0] for c in calls]
        assert any("test_results" in s for s in sql_statements)
        assert any("test_runs" in s for s in sql_statements)
        assert any("test_definitions" in s for s in sql_statements)
        assert any("test_suites" in s for s in sql_statements)
        assert any("data_contracts" in s for s in sql_statements)

    def test_only_contract_delete_when_no_snapshot_suite(self):
        """With no snapshot_suite_id: only 1 DELETE statement (contract row)."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 2}],              # version count
                       [{"snapshot_suite_id": None}],  # no snapshot suite
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(TG_ID, 0)

        calls = mock_exec.call_args[0][0]
        assert len(calls) == 1
        assert "data_contracts" in calls[0][0]

    def test_correct_tg_id_and_version_in_contract_delete(self):
        """Contract DELETE must be bound with correct table_group_id and version."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 2}],
                       [{"snapshot_suite_id": None}],
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(TG_ID, 5)

        calls = mock_exec.call_args[0][0]
        contract_delete = calls[0]
        params = contract_delete[1]
        assert params["tg_id"] == TG_ID
        assert params["version"] == 5

    def test_snapshot_suite_id_bound_in_suite_deletes(self):
        """snapshot_suite_id must be correctly bound in test_definitions and test_suites DELETEs."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 2}],
                       [{"snapshot_suite_id": SNAP_ID}],
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(TG_ID, 1)

        calls = mock_exec.call_args[0][0]
        # First 3 calls are suite-related deletes
        for i in range(3):
            params = calls[i][1]
            assert params.get("snapshot_suite_id") == SNAP_ID
