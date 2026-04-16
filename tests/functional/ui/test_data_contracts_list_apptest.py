"""Functional tests for DataContractsListPage. pytest -m functional"""
from __future__ import annotations
import pathlib
import pytest
from streamlit.testing.v1 import AppTest

pytestmark = pytest.mark.functional

APP = "tests/functional/ui/apps/data_contracts_list_app.py"
APP_EMPTY = str(pathlib.Path(__file__).parent / "apps" / "data_contracts_list_empty_app.py")


def _at() -> AppTest:
    return AppTest.from_file(APP, default_timeout=15)


def _at_empty() -> AppTest:
    return AppTest.from_file(APP_EMPTY, default_timeout=15)


def _all_markdown(at: AppTest) -> str:
    return " ".join(e.value for e in at.markdown)


def _button_labels(at: AppTest) -> list[str]:
    return [b.label for b in at.button]


# ---------------------------------------------------------------------------
# Existing tests (kept for regression)
# ---------------------------------------------------------------------------

def test_list_page_renders_contract_names():
    at = _at()
    at.run()
    assert not at.exception
    assert "customer_quality" in _all_markdown(at)


def test_list_page_shows_toolbar_summary():
    at = _at()
    at.run()
    assert not at.exception
    caption_values = [c.value for c in at.caption]
    assert any("contract" in c.lower() for c in caption_values)


def test_list_page_groups_by_table_group():
    at = _at()
    at.run()
    assert not at.exception
    assert "customers_tg" in _all_markdown(at)


# ---------------------------------------------------------------------------
# Test_ListPageCards — card content for active and inactive contracts
# ---------------------------------------------------------------------------

class Test_ListPageCards:

    def test_both_contract_names_rendered(self):
        """Both sample contract names must appear somewhere in the rendered markdown."""
        at = _at()
        at.run()
        assert not at.exception
        text = _all_markdown(at)
        assert "customer_quality" in text, f"customer_quality not found in: {text[:300]}"
        assert "orders_validation" in text, f"orders_validation not found in: {text[:300]}"

    def test_active_contract_shows_passing_badge(self):
        """Active contract with Passing status must render '✓ Passing' badge in markdown."""
        at = _at()
        at.run()
        assert not at.exception
        text = _all_markdown(at)
        assert "Passing" in text, f"Expected 'Passing' badge in markdown. Got: {text[:500]}"

    def test_inactive_contract_shows_inactive_label(self):
        """Inactive contract must render 'Inactive' label in its card markdown."""
        at = _at()
        at.run()
        assert not at.exception
        text = _all_markdown(at)
        assert "Inactive" in text, f"Expected 'Inactive' label for inactive contract. Got: {text[:500]}"

    def test_contract_version_number_rendered(self):
        """Contract card must render the version number (v3 for customer_quality)."""
        at = _at()
        at.run()
        assert not at.exception
        text = _all_markdown(at)
        assert "v3" in text, f"Expected 'v3' in card markdown. Got: {text[:500]}"

    def test_contract_term_count_rendered(self):
        """Contract card must render the term count (42 for customer_quality)."""
        at = _at()
        at.run()
        assert not at.exception
        text = _all_markdown(at)
        assert "42" in text, f"Expected term count '42' in markdown. Got: {text[:500]}"

    def test_contract_test_count_rendered(self):
        """Contract card must render the test count (12 for customer_quality)."""
        at = _at()
        at.run()
        assert not at.exception
        text = _all_markdown(at)
        assert "12" in text, f"Expected test count '12' in markdown. Got: {text[:500]}"

    def test_detail_url_in_card_link(self):
        """Each card must contain an anchor href to the contract detail page."""
        at = _at()
        at.run()
        assert not at.exception
        text = _all_markdown(at)
        assert "/data-contract?contract_id=" in text, (
            f"Expected detail URL in card markdown. Got: {text[:500]}"
        )


# ---------------------------------------------------------------------------
# Test_ListPageButtons — toolbar and per-card action buttons
# ---------------------------------------------------------------------------

class Test_ListPageButtons:

    def test_new_contract_button_present(self):
        """'+ New Contract' toolbar button must be rendered."""
        at = _at()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert any("New Contract" in lbl for lbl in labels), (
            f"Expected '+ New Contract' button. Available: {labels}"
        )

    def test_active_contract_shows_delete_button(self):
        """Active contract must have a 'Delete' footer button (no Deactivate)."""
        at = _at()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Delete" in labels, (
            f"Expected 'Delete' button for active contract. Available: {labels}"
        )
        assert "Deactivate" not in labels, (
            f"'Deactivate' must not appear — it was removed. Available: {labels}"
        )

    def test_inactive_contract_shows_reactivate_button(self):
        """Inactive contract must have a 'Reactivate' footer button."""
        at = _at()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Reactivate" in labels, (
            f"Expected 'Reactivate' button for inactive contract. Available: {labels}"
        )

    def test_delete_button_present_for_each_contract(self):
        """Each contract card must have a 'Delete' button."""
        at = _at()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        delete_buttons = [lbl for lbl in labels if lbl == "Delete"]
        # Two contracts → two Delete buttons
        assert len(delete_buttons) == 2, (
            f"Expected 2 Delete buttons (one per contract). Found: {len(delete_buttons)}"
        )

    def test_no_deactivate_button_anywhere(self):
        """'Deactivate' was removed — must not appear for any contract."""
        at = _at()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert "Deactivate" not in labels, (
            f"'Deactivate' must not appear after removal. Found in: {labels}"
        )


# ---------------------------------------------------------------------------
# Test_ListPageToolbarSummary — caption counts
# ---------------------------------------------------------------------------

class Test_ListPageToolbarSummary:

    def test_summary_shows_contract_count(self):
        """Toolbar caption must include the total number of contracts (2)."""
        at = _at()
        at.run()
        assert not at.exception
        caption_values = [c.value for c in at.caption]
        assert any("2" in c for c in caption_values), (
            f"Expected '2' in caption for 2 contracts. Got: {caption_values}"
        )

    def test_summary_shows_table_group_count(self):
        """Toolbar caption must include the number of distinct table groups (1)."""
        at = _at()
        at.run()
        assert not at.exception
        caption_values = [c.value for c in at.caption]
        assert any("table group" in c.lower() for c in caption_values), (
            f"Expected 'table group' in caption. Got: {caption_values}"
        )


# ---------------------------------------------------------------------------
# Test_EmptyState — no contracts renders graceful empty state
# ---------------------------------------------------------------------------

class Test_EmptyState:

    def test_empty_state_renders_without_exception(self):
        """Empty contracts list must render without raising an exception."""
        at = _at_empty()
        at.run()
        assert not at.exception

    def test_empty_state_shows_info_message(self):
        """Empty state must show an info message prompting the user to create a contract."""
        at = _at_empty()
        at.run()
        assert not at.exception
        info_texts = [i.value for i in at.info]
        assert any("No contracts yet" in t or "New Contract" in t for t in info_texts), (
            f"Expected empty-state info message. Got: {info_texts}"
        )

    def test_empty_state_new_contract_button_present(self):
        """'+ New Contract' button must still appear in the toolbar on empty state."""
        at = _at_empty()
        at.run()
        assert not at.exception
        labels = _button_labels(at)
        assert any("New Contract" in lbl for lbl in labels), (
            f"Expected '+ New Contract' in empty state. Available: {labels}"
        )

    def test_empty_state_has_no_contract_cards(self):
        """Empty state must render no contract names in markdown."""
        at = _at_empty()
        at.run()
        assert not at.exception
        text = _all_markdown(at)
        # The two sample contract names from the main fixture must NOT appear
        assert "customer_quality" not in text
        assert "orders_validation" not in text

    def test_empty_state_caption_shows_zero_contracts(self):
        """Toolbar caption must show '0 contracts' when there are none."""
        at = _at_empty()
        at.run()
        assert not at.exception
        caption_values = [c.value for c in at.caption]
        assert any("0 contract" in c for c in caption_values), (
            f"Expected '0 contract' in caption. Got: {caption_values}"
        )
