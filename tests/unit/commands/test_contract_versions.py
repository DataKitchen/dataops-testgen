"""
Unit tests for contract version management.
pytest -m unit tests/unit/commands/test_contract_versions.py
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

pytestmark = pytest.mark.unit

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
            assert has_any_version(TG_ID) is True

    def test_returns_false_when_no_rows(self):
        from testgen.commands.contract_versions import has_any_version

        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[]):
            assert has_any_version(TG_ID) is False


# ---------------------------------------------------------------------------
# load_contract_version
# ---------------------------------------------------------------------------

class Test_LoadContractVersion:
    _SAVED_AT = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_returns_none_when_not_found(self):
        from testgen.commands.contract_versions import load_contract_version

        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[]):
            assert load_contract_version(TG_ID) is None

    def test_returns_dict_with_correct_keys_for_latest(self):
        from testgen.commands.contract_versions import load_contract_version

        row = {
            "version": 2,
            "saved_at": self._SAVED_AT,
            "label": "v2-label",
            "contract_yaml": "apiVersion: v3.1.0\n",
        }
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[row]):
            result = load_contract_version(TG_ID)

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
        }
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[row]):
            result = load_contract_version(TG_ID, version=1)

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
        }
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=[row]):
            result = load_contract_version(TG_ID)

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
            assert list_contract_versions(TG_ID) == []

    def test_returns_versions_newest_first(self):
        from testgen.commands.contract_versions import list_contract_versions

        rows = [
            {"version": 2, "saved_at": self._SAVED_AT, "label": "latest"},
            {"version": 1, "saved_at": self._SAVED_AT, "label": None},
            {"version": 0, "saved_at": self._SAVED_AT, "label": "initial"},
        ]
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=rows):
            result = list_contract_versions(TG_ID)

        assert len(result) == 3
        assert result[0]["version"] == 2
        assert result[1]["version"] == 1
        assert result[2]["version"] == 0

    def test_each_entry_has_version_saved_at_label(self):
        from testgen.commands.contract_versions import list_contract_versions

        rows = [
            {"version": 0, "saved_at": self._SAVED_AT, "label": "first"},
            {"version": 1, "saved_at": self._SAVED_AT, "label": None},
        ]
        with patch("testgen.commands.contract_versions.fetch_dict_from_db", return_value=rows):
            result = list_contract_versions(TG_ID)

        for entry in result:
            assert "version" in entry
            assert "saved_at" in entry
            assert "label" in entry


# ---------------------------------------------------------------------------
# save_contract_version
# ---------------------------------------------------------------------------

class Test_SaveContractVersion:
    def _run_save(self, return_values, row_counts, label=None):
        from testgen.commands.contract_versions import save_contract_version

        # execute_db_queries is called twice: first for INSERT (returns version),
        # then for UPDATE (clears stale flag). Side-effect supplies return values
        # for each call in order.
        side_effects = [
            (return_values, row_counts),
            ([], [1]),
        ]
        with patch(
            "testgen.commands.contract_versions.execute_db_queries",
            side_effect=side_effects,
        ) as mock_exec:
            result = save_contract_version(TG_ID, "yaml-content", label=label)
            return result, mock_exec

    def test_first_save_returns_zero(self):
        result, _ = self._run_save([0], [1])
        assert result == 0

    def test_second_save_returns_one(self):
        result, _ = self._run_save([1], [1])
        assert result == 1

    def test_executes_two_queries(self):
        """INSERT and UPDATE are now issued as two separate execute_db_queries calls."""
        _, mock_exec = self._run_save([0], [1])
        assert mock_exec.call_count == 2

    def test_insert_query_contains_returning(self):
        _, mock_exec = self._run_save([0], [1])
        # First call is the INSERT
        insert_queries = mock_exec.call_args_list[0][0][0]
        insert_sql = insert_queries[0][0]
        assert "RETURNING" in insert_sql.upper()

    def test_update_clears_stale_flag(self):
        _, mock_exec = self._run_save([0], [1])
        # Second call is the UPDATE
        update_queries = mock_exec.call_args_list[1][0][0]
        update_sql = update_queries[0][0]
        assert "contract_stale" in update_sql
        assert "FALSE" in update_sql.upper()

    def test_label_passed_as_param(self):
        _, mock_exec = self._run_save([0], [1], label="my-label")
        # First call is the INSERT
        insert_queries = mock_exec.call_args_list[0][0][0]
        insert_params = insert_queries[0][1]
        assert insert_params.get("label") == "my-label"


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


# ---------------------------------------------------------------------------
# mark_contract_not_stale
# ---------------------------------------------------------------------------

class Test_MarkContractNotStale:
    def test_sets_stale_false(self):
        from testgen.commands.contract_versions import mark_contract_not_stale

        with patch(
            "testgen.commands.contract_versions.execute_db_queries",
            return_value=([], [1]),
        ) as mock_exec:
            mark_contract_not_stale(TG_ID)

        queries = mock_exec.call_args[0][0]
        sql = queries[0][0]
        assert "contract_stale" in sql
        assert "FALSE" in sql.upper()
