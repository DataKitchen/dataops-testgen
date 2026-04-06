"""
Unit tests for staleness flag logic (mark_contract_stale / mark_contract_not_stale
plus save_contract_version resetting the stale flag).

pytest -m unit tests/unit/commands/test_staleness_detection.py
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Strip decorators
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
# Test_StalenessSignals
# ---------------------------------------------------------------------------

class Test_StalenessSignals:
    def test_mark_stale_updates_correct_table_group(self):
        """SQL params contain the supplied table_group_id."""
        from testgen.commands.contract_versions import mark_contract_stale

        with patch(
            "testgen.commands.contract_versions.execute_db_queries",
            return_value=([], [1]),
        ) as mock_exec:
            mark_contract_stale("abc")

        queries = mock_exec.call_args[0][0]
        params = queries[0][1]
        assert params.get("tg_id") == "abc"

    def test_mark_stale_only_when_save_date_present(self):
        """UPDATE WHERE clause includes last_contract_save_date IS NOT NULL guard."""
        from testgen.commands.contract_versions import mark_contract_stale

        with patch(
            "testgen.commands.contract_versions.execute_db_queries",
            return_value=([], [1]),
        ) as mock_exec:
            mark_contract_stale(TG_ID)

        queries = mock_exec.call_args[0][0]
        sql = queries[0][0]
        assert "last_contract_save_date IS NOT NULL" in sql

    def test_mark_not_stale_sets_false(self):
        """mark_contract_not_stale emits SQL with contract_stale = FALSE."""
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


# ---------------------------------------------------------------------------
# Test_StalenessResetOnSave
# ---------------------------------------------------------------------------

class Test_StalenessResetOnSave:
    def test_save_clears_stale_flag(self):
        """save_contract_version includes a query that sets contract_stale = FALSE."""
        from testgen.commands.contract_versions import save_contract_version

        with patch(
            "testgen.commands.contract_versions.execute_db_queries",
            return_value=([0], [1]),
        ) as mock_exec:
            save_contract_version(TG_ID, "yaml-content")

        queries = mock_exec.call_args[0][0]
        # At least one query must set contract_stale = FALSE
        stale_sqls = [q[0] for q in queries if "contract_stale" in q[0] and "FALSE" in q[0].upper()]
        assert stale_sqls, "Expected at least one query setting contract_stale = FALSE"

    def test_save_sets_last_save_date(self):
        """save_contract_version includes a query that sets last_contract_save_date = NOW()."""
        from testgen.commands.contract_versions import save_contract_version

        with patch(
            "testgen.commands.contract_versions.execute_db_queries",
            return_value=([0], [1]),
        ) as mock_exec:
            save_contract_version(TG_ID, "yaml-content")

        queries = mock_exec.call_args[0][0]
        now_sqls = [q[0] for q in queries if "last_contract_save_date" in q[0]]
        assert now_sqls, "Expected at least one query referencing last_contract_save_date"
        # The value should be NOW() (or equivalent)
        assert any("NOW()" in sql.upper() or "now()" in sql for sql in now_sqls)
