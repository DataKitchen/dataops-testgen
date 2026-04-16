# tests/unit/commands/test_contracts_list_queries.py
"""Tests for data_contract_list_queries.py. pytest -m unit"""
from __future__ import annotations
from unittest.mock import patch
import pytest

pytestmark = pytest.mark.unit

PROJECT = "P1"
TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    monkeypatch.setattr(
        "testgen.ui.queries.data_contract_list_queries.with_database_session", lambda f: f
    )
    monkeypatch.setattr(
        "testgen.ui.queries.data_contract_list_queries.get_tg_schema", lambda: "tg"
    )


class Test_FetchContractsForProject:
    def test_returns_list_of_dicts(self):
        from testgen.ui.queries.data_contract_list_queries import fetch_contracts_for_project
        row = {
            "contract_id": "ccc", "name": "my_contract", "is_active": True,
            "table_group_id": TG_ID, "table_group_name": "tg1",
            "version": 1, "term_count": 42, "version_count": 2,
            "test_count": 10, "status": "Passing",
        }
        with patch("testgen.ui.queries.data_contract_list_queries.fetch_dict_from_db", return_value=[row]):
            result = fetch_contracts_for_project(PROJECT)
        assert len(result) == 1
        assert result[0]["name"] == "my_contract"

    def test_sql_filters_by_project_code(self):
        from testgen.ui.queries.data_contract_list_queries import fetch_contracts_for_project
        with patch("testgen.ui.queries.data_contract_list_queries.fetch_dict_from_db", return_value=[]) as m:
            fetch_contracts_for_project(PROJECT)
        sql = m.call_args[0][0]
        assert "project_code" in sql

    def test_inactive_contracts_included(self):
        from testgen.ui.queries.data_contract_list_queries import fetch_contracts_for_project
        rows = [
            {"contract_id": "c1", "name": "active", "is_active": True, "table_group_id": TG_ID,
             "table_group_name": "tg1", "version": 1, "term_count": 5, "version_count": 1,
             "test_count": 3, "status": "Passing"},
            {"contract_id": "c2", "name": "inactive", "is_active": False, "table_group_id": TG_ID,
             "table_group_name": "tg1", "version": 0, "term_count": 0, "version_count": 1,
             "test_count": 0, "status": "No Run"},
        ]
        with patch("testgen.ui.queries.data_contract_list_queries.fetch_dict_from_db", return_value=rows):
            result = fetch_contracts_for_project(PROJECT)
        assert len(result) == 2

    def test_sql_does_not_filter_out_inactive(self):
        from testgen.ui.queries.data_contract_list_queries import fetch_contracts_for_project
        with patch("testgen.ui.queries.data_contract_list_queries.fetch_dict_from_db", return_value=[]) as m:
            fetch_contracts_for_project(PROJECT)
        sql = m.call_args[0][0].lower()
        # Must NOT have a WHERE clause that restricts to active only
        assert "is_active = true" not in sql
        assert "is_active=true" not in sql
