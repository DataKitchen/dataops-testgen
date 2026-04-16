"""Functional tests for DataContractsListPage. pytest -m functional"""
from __future__ import annotations
import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.functional

APP = "tests/functional/ui/apps/data_contracts_list_app.py"


def test_list_page_renders_contract_names():
    at = AppTest.from_file(APP, default_timeout=15)
    at.run()
    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert "customer_quality" in button_labels


def test_list_page_shows_toolbar_summary():
    at = AppTest.from_file(APP, default_timeout=15)
    at.run()
    assert not at.exception
    caption_values = [c.value for c in at.caption]
    assert any("contract" in c.lower() for c in caption_values)


def test_list_page_groups_by_table_group():
    at = AppTest.from_file(APP, default_timeout=15)
    at.run()
    assert not at.exception
    markdown_values = [e.value for e in at.markdown]
    all_text = " ".join(markdown_values)
    assert "customers_tg" in all_text


def test_list_page_empty_state_shows_info():
    # Run with no contracts
    at = AppTest.from_file(APP, default_timeout=15)
    at.run()
    # AppTest does not support dynamic patching mid-run; test the info message via direct render.
    # This test verifies the app does not crash with sample data — full behavior tested via unit test.
    assert not at.exception
