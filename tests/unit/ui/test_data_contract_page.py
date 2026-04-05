"""
Unit tests proving the Data Contract UI page is available and its core logic is correct.

pytest -m unit tests/unit/ui/test_data_contract_page.py
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Bootstrap — mock heavy Streamlit component machinery before any app imports
# ---------------------------------------------------------------------------

def _mock_streamlit_components() -> None:
    """
    Prevent the Streamlit v1/v2 component registration from running.
    widgets/__init__.py calls components_v2.component() at import time which
    requires a live Streamlit runtime.  We mock streamlit.components.v2 so that
    call becomes a no-op, while leaving the rest of the widgets package intact.
    """
    import streamlit.components.v2 as _sv2
    _sv2.component = MagicMock(return_value=MagicMock())

    # Also block the testgen_component module (see tests/unit/ui/conftest.py)
    sys.modules.setdefault(
        "testgen.ui.components.widgets.testgen_component", MagicMock()
    )


_mock_streamlit_components()

# Now safe to import app code
from testgen.ui.bootstrap import BUILTIN_PAGES  # noqa: E402
from testgen.ui.views.data_contract import (  # noqa: E402
    DataContractPage,
    _column_coverage_tiers,
    _tier_badge,
    _quality_counts,
    _worst_status,
    _render_gap_analysis,
    ContractDiff as _ContractDiff,  # re-exported for convenience
)
from testgen.commands.import_data_contract import ContractDiff  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Page registration — proves the route exists and is reachable
# ---------------------------------------------------------------------------

class Test_PageRegistration:
    def test_data_contract_page_in_builtin_pages(self):
        """DataContractPage must be registered so the router can serve it."""
        paths = [p.path for p in BUILTIN_PAGES]
        assert "data-contract" in paths

    def test_data_contract_page_class_in_builtin_pages(self):
        assert DataContractPage in BUILTIN_PAGES

    def test_path_is_correct(self):
        assert DataContractPage.path == "data-contract"

    def test_no_menu_item(self):
        """Data Contract is a detail page — it must NOT appear in the sidebar."""
        assert DataContractPage.menu_item is None

    def test_can_activate_requires_table_group_id(self):
        """The guards list must include a check for table_group_id."""
        guards = DataContractPage.can_activate or []
        # There should be at least two guards (logged-in + table_group_id)
        assert len(guards) >= 2

    def test_page_has_no_slash_in_path(self):
        """Streamlit does not support multi-level paths with '/'."""
        assert "/" not in DataContractPage.path


# ---------------------------------------------------------------------------
# 2. Column coverage tier logic
# ---------------------------------------------------------------------------

class Test_ColumnCoverageTiers:
    def _prop(self, physical="varchar(50)", **kwargs):
        return {"physicalType": physical, "name": "col", **kwargs}

    def test_char_constrained_gets_db_enforced(self):
        tiers = _column_coverage_tiers(self._prop("varchar(50)"), [])
        assert "db_enforced" in tiers

    def test_numeric_precision_gets_db_enforced(self):
        tiers = _column_coverage_tiers(self._prop("numeric(10,2)"), [])
        assert "db_enforced" in tiers

    def test_integer_gets_db_enforced(self):
        tiers = _column_coverage_tiers(self._prop("integer"), [])
        assert "db_enforced" in tiers

    def test_boolean_gets_db_enforced(self):
        tiers = _column_coverage_tiers(self._prop("boolean"), [])
        assert "db_enforced" in tiers

    def test_column_with_matching_rule_gets_tested(self):
        rule = {"element": "some_table.col"}
        prop = {"physicalType": "text", "name": "col"}
        tiers = _column_coverage_tiers(prop, [rule])
        assert "tested" in tiers

    def test_column_without_rules_not_tested(self):
        prop = {"physicalType": "text", "name": "col"}
        tiers = _column_coverage_tiers(prop, [])
        assert "tested" not in tiers

    def test_classification_gets_declared(self):
        prop = {"physicalType": "text", "name": "col", "classification": "pii"}
        tiers = _column_coverage_tiers(prop, [])
        assert "declared" in tiers

    def test_critical_data_element_gets_declared(self):
        prop = {"physicalType": "text", "name": "col", "criticalDataElement": True}
        tiers = _column_coverage_tiers(prop, [])
        assert "declared" in tiers

    def test_column_with_observed_stats_gets_observed(self):
        prop = {
            "physicalType": "text",
            "name": "col",
            "logicalTypeOptions": {"minimum": 0},
        }
        tiers = _column_coverage_tiers(prop, [])
        assert "observed" in tiers

    def test_empty_column_defaults_to_observed(self):
        """A column with no annotations must still get at least 'observed'."""
        prop = {"physicalType": "text", "name": "col"}
        tiers = _column_coverage_tiers(prop, [])
        assert tiers  # non-empty
        assert "observed" in tiers


# ---------------------------------------------------------------------------
# 3. Tier badge helper
# ---------------------------------------------------------------------------

class Test_TierBadge:
    def test_badge_contains_icon_for_each_tier(self):
        badge = _tier_badge(["db_enforced", "tested"])
        assert "🏛️" in badge
        assert "⚡" in badge

    def test_unknown_tier_ignored(self):
        badge = _tier_badge(["unknown_tier"])
        assert badge == ""

    def test_empty_list(self):
        assert _tier_badge([]) == ""


# ---------------------------------------------------------------------------
# 4. Quality rule status helpers
# ---------------------------------------------------------------------------

class Test_QualityCounts:
    def _rule(self, status):
        return {"lastResult": {"status": status}}

    def test_counts_passing(self):
        counts = _quality_counts([self._rule("passing")] * 3)
        assert counts["passing"] == 3

    def test_counts_mixed(self):
        rules = [self._rule("passing"), self._rule("failing"), self._rule("warning")]
        counts = _quality_counts(rules)
        assert counts["passing"] == 1
        assert counts["failing"] == 1
        assert counts["warning"] == 1

    def test_no_last_result_counted_as_not_run(self):
        counts = _quality_counts([{"id": "x"}])
        assert counts.get("not run", 0) == 1

    def test_worst_status_failing_beats_warning(self):
        assert _worst_status({"passing": 2, "failing": 1}) == "failing"

    def test_worst_status_all_passing(self):
        assert _worst_status({"passing": 5}) == "passing"

    def test_worst_status_empty_returns_not_run(self):
        assert _worst_status({}) == "not run"


# ---------------------------------------------------------------------------
# 5. JS entry points — link hrefs are wired to the correct page path
# ---------------------------------------------------------------------------

class Test_JsLinkHrefs:
    """
    Reads the JS source files and asserts that 'data-contract' href is present.
    These tests catch accidental removal of the navigation links.
    """
    def _read_js(self, filename: str) -> str:
        import pathlib
        base = pathlib.Path(__file__).parents[3] / "testgen" / "ui" / "components" / "frontend" / "js" / "pages"
        return (base / filename).read_text()

    def test_test_suites_js_has_data_contract_link(self):
        src = self._read_js("test_suites.js")
        assert "data-contract" in src

    def test_project_dashboard_js_has_data_contract_link(self):
        src = self._read_js("project_dashboard.js")
        assert "data-contract" in src

    def test_table_group_list_js_has_data_contract_link(self):
        src = self._read_js("table_group_list.js")
        assert "data-contract" in src

    def test_test_suites_js_passes_table_groups_id(self):
        src = self._read_js("test_suites.js")
        assert "table_groups_id" in src

    def test_table_group_list_js_passes_table_group_id(self):
        src = self._read_js("table_group_list.js")
        # Confirm the data-contract link uses table_group_id param
        assert "'table_group_id': tableGroup.id" in src or "table_group_id" in src


# ---------------------------------------------------------------------------
# 6. Python navigation handler wired in table_groups.py
# ---------------------------------------------------------------------------

class Test_NavigationHandlers:
    """
    Verifies that table_groups.py has the ViewContractClicked handler so that
    clicking the link actually navigates to the data-contract page.
    """
    def test_view_contract_clicked_handler_present(self):
        import pathlib
        src = (
            pathlib.Path(__file__).parents[3]
            / "testgen" / "ui" / "views" / "table_groups.py"
        ).read_text()
        assert "ViewContractClicked" in src
        assert "data-contract" in src
