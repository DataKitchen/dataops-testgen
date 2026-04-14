"""
Unit tests for contract snapshot suite creation and sync.
pytest -m unit tests/unit/commands/test_contract_snapshot_suite.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SNAP_ID = "bbbbbbbb-0000-0000-0000-000000000002"
NEW_SUITE_ID = "cccccccc-0000-0000-0000-000000000003"


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


@pytest.fixture(autouse=True)
def patch_uuid(monkeypatch):
    """Return a deterministic UUID so we can assert on it."""
    monkeypatch.setattr(
        "testgen.commands.contract_snapshot_suite.uuid.uuid4",
        lambda: MagicMock(__str__=lambda self: NEW_SUITE_ID),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fetch_side_effect(
    tg_name: str = "My Group",
    source_count: int = 5,
    has_suites: bool = True,
):
    """Return a side_effect list for fetch_dict_from_db calls in create_contract_snapshot_suite."""
    suite_info = [{"connection_id": 1, "project_code": "proj", "severity": None}] if has_suites else []
    return [
        [{"table_groups_name": tg_name}],          # table_groups lookup
        [{"ct": source_count}],                    # count check
        suite_info,                                # source suite lookup
    ]


# ---------------------------------------------------------------------------
# create_contract_snapshot_suite
# ---------------------------------------------------------------------------

class Test_CreateContractSnapshotSuite:

    def test_suite_name_format(self):
        """Suite name must be [Contract v{N}] {table_group_name}."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect("My Group")), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 2)

        calls = mock_exec.call_args[0][0]
        # The suite name is a param bound across all three queries
        params = calls[0][1]
        assert params["suite_name"] == "[Contract v2] My Group"

    def test_is_contract_snapshot_true_in_suite_insert(self):
        """The INSERT into test_suites must set is_contract_snapshot = TRUE."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 0)

        calls = mock_exec.call_args[0][0]
        suite_insert_sql = calls[0][0]
        assert "is_contract_snapshot" in suite_insert_sql
        assert "TRUE" in suite_insert_sql.upper()

    def test_include_in_contract_true_in_suite_insert(self):
        """The INSERT into test_suites must set include_in_contract = TRUE."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 0)

        calls = mock_exec.call_args[0][0]
        suite_insert_sql = calls[0][0]
        assert "include_in_contract" in suite_insert_sql
        assert "TRUE" in suite_insert_sql.upper()

    def test_source_test_definition_id_set_in_bulk_copy(self):
        """The bulk INSERT … SELECT must set source_test_definition_id = td.id."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 1)

        calls = mock_exec.call_args[0][0]
        bulk_copy_sql = calls[1][0]
        assert "source_test_definition_id" in bulk_copy_sql
        assert "td.id" in bulk_copy_sql

    def test_data_contracts_snapshot_suite_id_updated(self):
        """The UPDATE data_contracts must set snapshot_suite_id."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 1)

        calls = mock_exec.call_args[0][0]
        update_sql = calls[2][0]
        assert "snapshot_suite_id" in update_sql
        assert "data_contracts" in update_sql

    def test_monitor_suites_excluded_from_bulk_copy(self):
        """Bulk copy SQL must exclude is_monitor suites."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 0)

        calls = mock_exec.call_args[0][0]
        bulk_copy_sql = calls[1][0]
        assert "is_monitor" in bulk_copy_sql.lower()
        assert "FALSE" in bulk_copy_sql.upper()

    def test_existing_snapshot_suites_excluded_from_bulk_copy(self):
        """Bulk copy SQL must exclude is_contract_snapshot suites."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 0)

        calls = mock_exec.call_args[0][0]
        bulk_copy_sql = calls[1][0]
        assert "is_contract_snapshot" in bulk_copy_sql

    def test_include_in_contract_false_suites_excluded(self):
        """Bulk copy SQL must exclude suites with include_in_contract = FALSE."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 0)

        calls = mock_exec.call_args[0][0]
        bulk_copy_sql = calls[1][0]
        assert "include_in_contract" in bulk_copy_sql

    def test_single_execute_db_queries_call_with_three_statements(self):
        """All three SQL statements must be passed to a single execute_db_queries call."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 0)

        assert mock_exec.call_count == 1
        calls = mock_exec.call_args[0][0]
        assert len(calls) == 3

    def test_raises_value_error_when_no_in_scope_tests(self):
        """Must raise ValueError when source test count = 0."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect(source_count=0)):
            with pytest.raises(ValueError, match="No in-scope tests"):
                create_contract_snapshot_suite(TG_ID, 0)

    def test_data_contracts_update_uses_table_group_id_singular(self):
        """data_contracts uses table_group_id (singular), not table_groups_id.
        Regression test for UndefinedColumn error on regenerate+save."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 1)

        calls = mock_exec.call_args[0][0]
        update_sql = calls[2][0]
        # Must use singular table_group_id for data_contracts table
        assert "table_group_id" in update_sql
        assert "table_groups_id" not in update_sql

    def test_bulk_copy_uses_on_conflict_do_nothing(self):
        """Bulk copy SQL must use ON CONFLICT DO NOTHING so duplicate test types
        across multiple source suites (e.g. LOV_Match on the same column in two
        suites) do not cause a unique constraint violation on save/regenerate."""
        from testgen.commands.contract_snapshot_suite import create_contract_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.fetch_dict_from_db",
                   side_effect=_make_fetch_side_effect()), \
             patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            create_contract_snapshot_suite(TG_ID, 1)

        calls = mock_exec.call_args[0][0]
        bulk_copy_sql = calls[1][0].upper()
        assert "ON CONFLICT DO NOTHING" in bulk_copy_sql


# ---------------------------------------------------------------------------
# sync_import_to_snapshot_suite
# ---------------------------------------------------------------------------

class Test_SyncImportToSnapshotSuite:

    def test_created_ids_produce_insert(self):
        """Created IDs must produce an INSERT INTO snapshot suite with source_test_definition_id."""
        from testgen.commands.contract_snapshot_suite import sync_import_to_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            sync_import_to_snapshot_suite(
                SNAP_ID,
                created_td_ids=["td-1", "td-2"],
                updated_td_ids=[],
                deleted_td_ids=[],
            )

        assert mock_exec.call_count == 1
        calls = mock_exec.call_args[0][0]
        insert_sql = calls[0][0]
        assert "INSERT" in insert_sql.upper()
        assert "source_test_definition_id" in insert_sql

    def test_updated_ids_produce_update(self):
        """Updated IDs must produce an UPDATE on snapshot rows matching source_test_definition_id."""
        from testgen.commands.contract_snapshot_suite import sync_import_to_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            sync_import_to_snapshot_suite(
                SNAP_ID,
                created_td_ids=[],
                updated_td_ids=["td-3"],
                deleted_td_ids=[],
            )

        calls = mock_exec.call_args[0][0]
        update_sql = calls[0][0]
        assert "UPDATE" in update_sql.upper()
        assert "source_test_definition_id" in update_sql

    def test_deleted_ids_produce_delete(self):
        """Deleted IDs must produce a DELETE on snapshot rows matching source_test_definition_id."""
        from testgen.commands.contract_snapshot_suite import sync_import_to_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            sync_import_to_snapshot_suite(
                SNAP_ID,
                created_td_ids=[],
                updated_td_ids=[],
                deleted_td_ids=["td-4"],
            )

        calls = mock_exec.call_args[0][0]
        delete_sql = calls[0][0]
        assert "DELETE" in delete_sql.upper()
        assert "source_test_definition_id" in delete_sql

    def test_empty_lists_no_db_call(self):
        """All-empty lists must result in zero execute_db_queries calls."""
        from testgen.commands.contract_snapshot_suite import sync_import_to_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            sync_import_to_snapshot_suite(
                SNAP_ID,
                created_td_ids=[],
                updated_td_ids=[],
                deleted_td_ids=[],
            )

        mock_exec.assert_not_called()

    def test_none_snapshot_id_is_noop_at_call_site(self):
        """Callers guard against None snapshot_suite_id — not the function itself.
        This test documents the call-site pattern: don't call when None."""
        from testgen.commands.contract_snapshot_suite import sync_import_to_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            # Simulate call-site guard: only call when snapshot_suite_id is not None
            snapshot_suite_id: str | None = None
            if snapshot_suite_id:
                sync_import_to_snapshot_suite(snapshot_suite_id, ["td-1"], [], [])

        mock_exec.assert_not_called()

    def test_mixed_ops_single_execute_db_queries_call(self):
        """Create + update + delete ops must all be in a single execute_db_queries call."""
        from testgen.commands.contract_snapshot_suite import sync_import_to_snapshot_suite

        with patch("testgen.commands.contract_snapshot_suite.execute_db_queries",
                   return_value=([], [])) as mock_exec:
            sync_import_to_snapshot_suite(
                SNAP_ID,
                created_td_ids=["c1"],
                updated_td_ids=["u1"],
                deleted_td_ids=["d1"],
            )

        assert mock_exec.call_count == 1
        calls = mock_exec.call_args[0][0]
        assert len(calls) == 3
        sql_types = {calls[0][0].strip()[:6].upper(), calls[1][0].strip()[:6].upper(), calls[2][0].strip()[:6].upper()}
        assert "INSERT" in sql_types
        assert "UPDATE" in sql_types
        assert "DELETE" in sql_types
