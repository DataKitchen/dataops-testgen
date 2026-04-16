"""
Unit tests for delete_contract_version.
pytest -m unit tests/unit/commands/test_delete_contract_version.py
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

CONTRACT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
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
                delete_contract_version(CONTRACT_ID, 0)

    def test_five_delete_statements_when_snapshot_suite_present(self):
        """With snapshot_suite_id and non-current version: 4 suite DELETEs + 1 contract_versions DELETE = 5 total."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 3}],                                                    # version count
                       [{"snapshot_suite_id": SNAP_ID, "is_current": False}],          # version info
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(CONTRACT_ID, 1)

        assert mock_exec.call_count == 1
        calls = mock_exec.call_args[0][0]
        assert len(calls) == 5
        sql_statements = [c[0] for c in calls]
        assert any("test_results" in s for s in sql_statements)
        assert any("test_runs" in s for s in sql_statements)
        assert any("test_definitions" in s for s in sql_statements)
        assert any("test_suites" in s for s in sql_statements)
        assert any("contract_versions" in s for s in sql_statements)

    def test_only_contract_delete_when_no_snapshot_suite(self):
        """With no snapshot_suite_id and non-current version: only 1 DELETE statement (contract_versions row)."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 2}],
                       [{"snapshot_suite_id": None, "is_current": False}],
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(CONTRACT_ID, 0)

        calls = mock_exec.call_args[0][0]
        assert len(calls) == 1
        assert "contract_versions" in calls[0][0]

    def test_correct_contract_id_and_version_in_delete(self):
        """contract_versions DELETE must be bound with correct contract_id and version."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 2}],
                       [{"snapshot_suite_id": None, "is_current": False}],
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(CONTRACT_ID, 5)

        calls = mock_exec.call_args[0][0]
        contract_delete = calls[0]
        params = contract_delete[1]
        assert params["contract_id"] == CONTRACT_ID
        assert params["version"] == 5

    def test_snapshot_suite_id_bound_in_suite_deletes(self):
        """snapshot_suite_id must be correctly bound in test_definitions and test_suites DELETEs."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 2}],
                       [{"snapshot_suite_id": SNAP_ID, "is_current": False}],
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(CONTRACT_ID, 1)

        calls = mock_exec.call_args[0][0]
        # First 4 calls are suite-related deletes (test_results, test_runs, test_definitions, test_suites)
        for i in range(4):
            params = calls[i][1]
            assert params.get("sid") == SNAP_ID

    def test_promotes_previous_version_when_deleting_current(self):
        """Deleting the is_current=TRUE version must prepend an UPDATE to promote the previous version."""
        from testgen.commands.contract_snapshot_suite import delete_contract_version

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=[
                       [{"ct": 2}],
                       [{"snapshot_suite_id": None, "is_current": True}],
                   ]), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            delete_contract_version(CONTRACT_ID, 3)

        calls = mock_exec.call_args[0][0]
        # First statement must be the UPDATE to promote previous version
        assert "UPDATE" in calls[0][0]
        assert "is_current" in calls[0][0]
        # Last statement is the DELETE of contract_versions
        assert "contract_versions" in calls[-1][0]
        assert "DELETE" in calls[-1][0]
