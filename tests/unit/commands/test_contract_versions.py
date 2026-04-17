"""
Unit tests for contract version management.
pytest -m unit tests/unit/commands/test_contract_versions.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

pytestmark = pytest.mark.unit

CONTRACT_ID = "cccccccc-0000-0000-0000-000000000001"
TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Strip the DB session decorator so functions run without a real connection
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_session(monkeypatch):
    monkeypatch.setattr(
        "testgen.commands.contract_versions.with_database_session",
        lambda f: f,
    )
    monkeypatch.setattr(
        "testgen.commands.contract_versions.get_tg_schema",
        lambda: "tg",
    )


# ---------------------------------------------------------------------------
# has_any_version
# ---------------------------------------------------------------------------

class Test_HasAnyVersion:
    def test_returns_true_when_rows_exist(self):
        from testgen.commands.contract_versions import has_any_version

        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[{"1": 1}]):
            assert has_any_version(CONTRACT_ID) is True

    def test_returns_false_when_no_rows(self):
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


# ---------------------------------------------------------------------------
# load_contract_version
# ---------------------------------------------------------------------------

class Test_LoadContractVersion:
    _SAVED_AT = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_returns_none_when_not_found(self):
        from testgen.commands.contract_versions import load_contract_version

        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[]):
            assert load_contract_version(CONTRACT_ID) is None

    def test_returns_dict_with_correct_keys_for_latest(self):
        from testgen.commands.contract_versions import load_contract_version

        row = {
            "version": 2,
            "saved_at": self._SAVED_AT,
            "label": "v2-label",
            "contract_yaml": "apiVersion: v3.1.0\n",
            "snapshot_suite_id": None,
            "is_current": True,
        }
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[row]):
            result = load_contract_version(CONTRACT_ID)

        assert result is not None
        assert result["version"] == 2
        assert result["saved_at"] == self._SAVED_AT
        assert result["label"] == "v2-label"
        assert result["contract_yaml"] == "apiVersion: v3.1.0\n"

    def test_returns_specific_version(self):
        from testgen.commands.contract_versions import load_contract_version

        row = {
            "version": 1,
            "saved_at": self._SAVED_AT,
            "label": None,
            "contract_yaml": "yaml-content",
            "snapshot_suite_id": None,
            "is_current": False,
        }
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[row]):
            result = load_contract_version(CONTRACT_ID, version=1)

        assert result is not None
        assert result["version"] == 1

    def test_version_is_int(self):
        from testgen.commands.contract_versions import load_contract_version

        # Simulate DB returning a string-coercible value (e.g. from RowMapping)
        row = {
            "version": "3",
            "saved_at": self._SAVED_AT,
            "label": None,
            "contract_yaml": "yaml",
            "snapshot_suite_id": None,
            "is_current": True,
        }
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[row]):
            result = load_contract_version(CONTRACT_ID)

        assert result is not None
        assert isinstance(result["version"], int)
        assert result["version"] == 3


# ---------------------------------------------------------------------------
# list_contract_versions
# ---------------------------------------------------------------------------

class Test_ListContractVersions:
    _SAVED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_returns_empty_list_when_none(self):
        from testgen.commands.contract_versions import list_contract_versions

        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[]):
            assert list_contract_versions(CONTRACT_ID) == []

    def test_returns_versions_newest_first(self):
        from testgen.commands.contract_versions import list_contract_versions

        rows = [
            {"version": 2, "saved_at": self._SAVED_AT, "label": "latest", "is_current": True},
            {"version": 1, "saved_at": self._SAVED_AT, "label": None, "is_current": False},
            {"version": 0, "saved_at": self._SAVED_AT, "label": "initial", "is_current": False},
        ]
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=rows):
            result = list_contract_versions(CONTRACT_ID)

        assert len(result) == 3
        assert result[0]["version"] == 2
        assert result[1]["version"] == 1
        assert result[2]["version"] == 0

    def test_each_entry_has_version_saved_at_label(self):
        from testgen.commands.contract_versions import list_contract_versions

        rows = [
            {"version": 0, "saved_at": self._SAVED_AT, "label": "first", "is_current": False},
            {"version": 1, "saved_at": self._SAVED_AT, "label": None, "is_current": True},
        ]
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=rows):
            result = list_contract_versions(CONTRACT_ID)

        for entry in result:
            assert "version" in entry
            assert "saved_at" in entry
            assert "label" in entry


# ---------------------------------------------------------------------------
# save_contract_version
# ---------------------------------------------------------------------------

class Test_SaveContractVersion:
    def _run_save(self, return_values: list, row_counts: list, label: str | None = None):
        from testgen.commands.contract_versions import save_contract_version

        with patch(
            "testgen.commands.contract_versions.execute_db_queries",
            return_value=(return_values, row_counts),
        ) as mock_exec:
            result = save_contract_version(CONTRACT_ID, TG_ID, "yaml-content", label=label)
            return result, mock_exec

    def test_first_save_returns_zero(self):
        result, _ = self._run_save([0], [1])
        assert result == 0

    def test_second_save_returns_one(self):
        result, _ = self._run_save([1], [1])
        assert result == 1

    def test_single_query_used_not_two(self):
        """save_contract_version must use exactly one combined CTE query.

        Using one statement eliminates the fragile return_values index assumption
        that existed when flip UPDATE and INSERT were separate queries.
        """
        _, mock_exec = self._run_save([0], [1])
        queries = mock_exec.call_args[0][0]
        assert len(queries) == 1, (
            f"Expected 1 combined CTE query, got {len(queries)} queries"
        )

    def test_returns_int_from_index_zero(self):
        """save_contract_version reads return_values[0] from the single query."""
        result, _ = self._run_save([5], [1])
        assert result == 5

    def test_combined_sql_contains_flip_update_and_insert_returning(self):
        """The single CTE must contain UPDATE (flip), INSERT, and RETURNING."""
        _, mock_exec = self._run_save([0], [1])
        sql = mock_exec.call_args[0][0][0][0].upper()
        assert "UPDATE" in sql
        assert "INSERT" in sql
        assert "RETURNING" in sql

    def test_combined_sql_clears_staleness_flag(self):
        _, mock_exec = self._run_save([0], [1])
        sql = mock_exec.call_args[0][0][0][0].upper()
        assert "CONTRACT_STALE" in sql
        assert "FALSE" in sql

    def test_combined_sql_targets_contract_versions(self):
        _, mock_exec = self._run_save([0], [1])
        sql = mock_exec.call_args[0][0][0][0].upper()
        assert "CONTRACT_VERSIONS" in sql

    def test_label_passed_as_param(self):
        _, mock_exec = self._run_save([0], [1], label="my-label")
        params = mock_exec.call_args[0][0][0][1]
        assert params.get("label") == "my-label"


# ---------------------------------------------------------------------------
# mark_contract_stale
# ---------------------------------------------------------------------------

class Test_MarkContractStale:
    def _run(self):
        from testgen.commands.contract_versions import mark_contract_stale

        with patch(
            "testgen.commands.contract_versions.execute_db_queries",
            return_value=([], [1]),
        ) as mock_exec:
            mark_contract_stale(TG_ID)
            return mock_exec

    def test_sets_stale_true(self):
        mock_exec = self._run()
        queries = mock_exec.call_args[0][0]
        sql = queries[0][0]
        assert "contract_stale" in sql
        assert "TRUE" in sql.upper()

    def test_only_marks_when_save_date_not_null(self):
        mock_exec = self._run()
        queries = mock_exec.call_args[0][0]
        sql = queries[0][0]
        assert "last_contract_save_date IS NOT NULL" in sql

    def test_uses_correct_table_group_id(self):
        mock_exec = self._run()
        queries = mock_exec.call_args[0][0]
        params = queries[0][1]
        assert params.get("tg_id") == TG_ID

