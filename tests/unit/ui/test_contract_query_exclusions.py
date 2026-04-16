"""
Unit tests verifying that contract UI queries exclude snapshot suites.
pytest -m unit tests/unit/ui/test_contract_query_exclusions.py
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def patch_session(monkeypatch):
    monkeypatch.setattr(
        "testgen.ui.queries.data_contract_queries.with_database_session",
        lambda f: f,
    )
    monkeypatch.setattr(
        "testgen.ui.queries.data_contract_queries.get_tg_schema",
        lambda: "tg",
    )


class Test_ContractQueryExclusions:

    def test_fetch_suite_scope_excludes_snapshot_suites(self):
        """_fetch_suite_scope SQL must contain is_contract_snapshot IS NOT TRUE."""
        from testgen.ui.queries.data_contract_queries import _fetch_suite_scope

        captured: list[str] = []

        def _capture(sql, params=None, **_):
            captured.append(sql)
            return []

        with patch("testgen.ui.queries.data_contract_queries.fetch_dict_from_db", side_effect=_capture):
            _fetch_suite_scope(TG_ID)

        assert captured, "No SQL was captured"
        assert any("is_contract_snapshot" in s for s in captured), (
            "_fetch_suite_scope SQL does not exclude snapshot suites"
        )

    def test_fetch_test_statuses_excludes_snapshot_suites(self):
        """_fetch_test_statuses SQL must contain is_contract_snapshot check."""
        from testgen.ui.queries.data_contract_queries import _fetch_test_statuses

        captured: list[str] = []

        def _capture(sql, params=None, **_):
            captured.append(sql)
            return []

        with patch("testgen.ui.queries.data_contract_queries.fetch_dict_from_db", side_effect=_capture):
            _fetch_test_statuses(TG_ID)

        assert captured
        assert any("is_contract_snapshot" in s for s in captured), (
            "_fetch_test_statuses SQL does not exclude snapshot suites"
        )

    def test_fetch_last_run_dates_excludes_snapshot_suites(self):
        """_fetch_last_run_dates SQL must contain is_contract_snapshot check."""
        from testgen.ui.queries.data_contract_queries import _fetch_last_run_dates

        captured: list[str] = []

        def _capture(sql, params=None, **_):
            captured.append(sql)
            return []

        with patch("testgen.ui.queries.data_contract_queries.fetch_dict_from_db", side_effect=_capture):
            _fetch_last_run_dates(TG_ID)

        assert captured
        assert any("is_contract_snapshot" in s for s in captured), (
            "_fetch_last_run_dates SQL does not exclude snapshot suites"
        )

    def test_normal_suites_still_returned_by_fetch_suite_scope(self):
        """_fetch_suite_scope still returns non-snapshot suites correctly."""
        from testgen.ui.queries.data_contract_queries import _fetch_suite_scope

        rows = [
            {"test_suite": "suite_a", "include_in_contract": True},
            {"test_suite": "suite_b", "include_in_contract": False},
        ]
        with patch("testgen.ui.queries.data_contract_queries.fetch_dict_from_db", return_value=rows):
            result = _fetch_suite_scope(TG_ID)

        assert "suite_a" in result["included"]
        assert "suite_b" in result["excluded"]


def test_select_summary_sql_excludes_contract_suite_suites():
    """is_contract_suite=TRUE suites must not appear in TestSuite.select_summary."""
    import inspect
    from testgen.common.models.test_suite import TestSuite
    source = inspect.getsource(TestSuite.select_summary)
    assert "is_contract_suite" in source
