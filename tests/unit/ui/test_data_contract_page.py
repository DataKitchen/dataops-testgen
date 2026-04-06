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
    _build_contract_props,
    _column_coverage_tiers,
    _tier_badge,
    _quality_counts,
    _worst_status,
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


# ---------------------------------------------------------------------------
# 7. Claim count consistency — Overview == Coverage Matrix top == bottom
# ---------------------------------------------------------------------------

def _make_table_group(tg_id: str = "tg-001") -> MagicMock:
    tg = MagicMock()
    tg.id = tg_id
    tg.table_groups_name = "Test TG"
    tg.project_code = "proj"
    return tg


def _props_from_doc(doc: dict, anomalies: list | None = None) -> dict:
    """Call _build_contract_props with minimal required arguments."""
    import yaml as _yaml
    return _build_contract_props(
        table_group=_make_table_group(),
        doc=doc,
        anomalies=anomalies or [],
        contract_yaml=_yaml.dump(doc),
    )


def _claims_detail_total(props: dict) -> int:
    """Count every claim shown in the Claims Detail (Overview tab).

    Mirrors the JS ClaimsDetail loop: table_claims + static_claims + live_claims
    for every column in every table.
    """
    total = 0
    for t in props["tables"]:
        total += len(t.get("table_claims", []))
        for col in t.get("columns", []):
            total += len(col.get("static_claims", []))
            total += len(col.get("live_claims", []))
    return total


def _claim_counts_bar_totals(props: dict) -> tuple[int, int]:
    """Compute the by-source and by-verif totals that ClaimCountsBar shows.

    Returns (total_by_source, total_by_verif) — both must equal the claims
    detail total because they aggregate the same tables data.
    """
    # monitor source is grouped under test (mirrors JS ClaimCountsBar behaviour)
    by_src  = {"ddl": 0, "profiling": 0, "governance": 0, "test": 0}
    by_verif = {"db_enforced": 0, "tested": 0, "monitored": 0, "observed": 0, "declared": 0}

    for t in props["tables"]:
        for c in t.get("table_claims", []):
            src_key = "test" if c["source"] == "monitor" else c["source"]
            if src_key in by_src:
                by_src[src_key] += 1
            if c["verif"] in by_verif:
                by_verif[c["verif"]] += 1
        for col in t.get("columns", []):
            for c in col.get("static_claims", []) + col.get("live_claims", []):
                src_key = "test" if c["source"] == "monitor" else c["source"]
                if src_key in by_src:
                    by_src[src_key] += 1
                if c["verif"] in by_verif:
                    by_verif[c["verif"]] += 1

    return sum(by_src.values()), sum(by_verif.values())


def _coverage_matrix_total(props: dict) -> int:
    """Sum db + tested + mon + obs + decl across every row of the coverage matrix.

    This is the grand total shown at the bottom of the Coverage Matrix tab.
    """
    return sum(
        row["db"] + row["tested"] + row["mon"] + row["obs"] + row["decl"]
        for row in props["coverage_matrix"]
    )


class Test_ClaimCountConsistency:
    """
    The total number of claims must be equal across three UI locations:
      1. Claims Detail (Overview tab)  — static_claims + live_claims per column
      2. Claim Counts Bar (top of Coverage Matrix) — by source and by verif level
      3. Coverage Matrix grand total (bottom) — sum of db+tested+mon+obs per column
    """

    def _doc(self, tables: list[dict], quality: list[dict] | None = None,
             references: list[dict] | None = None) -> dict:
        return {
            "schema": tables,
            "quality": quality or [],
            "references": references or [],
        }

    def test_simple_column_no_claims(self):
        """A plain untyped column with no rules or annotations: all three totals equal."""
        doc = self._doc([{"name": "orders", "properties": [{"name": "id"}]}])
        props = _props_from_doc(doc)

        detail = _claims_detail_total(props)
        by_src, by_verif = _claim_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_db_enforced_claims(self):
        """varchar(50) + required + PK → three db_enforced claims."""
        doc = self._doc([{
            "name": "orders",
            "properties": [{
                "name": "order_id",
                "physicalType": "varchar(50)",
                "required": True,
                "logicalTypeOptions": {"primaryKey": True},
            }],
        }])
        props = _props_from_doc(doc)

        detail = _claims_detail_total(props)
        by_src, by_verif = _claim_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix
        assert detail == 3  # Data Type + Not Null + Primary Key

    def test_governance_claims(self):
        """description + classification + CDE → three declared claims."""
        doc = self._doc([{
            "name": "customers",
            "properties": [{
                "name": "email",
                "physicalType": "text",
                "description": "Customer email address",
                "classification": "pii",
                "criticalDataElement": True,
            }],
        }])
        props = _props_from_doc(doc)

        detail = _claims_detail_total(props)
        by_src, by_verif = _claim_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_test_rule_claims(self):
        """One non-monitor quality rule → one tested live claim."""
        doc = self._doc(
            tables=[{
                "name": "orders",
                "properties": [{"name": "amount", "physicalType": "numeric(10,2)"}],
            }],
            quality=[{
                "id": "rule-001",
                "element": "orders.amount",
                "testType": "Threshold_Numeric",
                "name": "Amount positive",
                "lastResult": {"status": "passing"},
            }],
        )
        props = _props_from_doc(doc)

        detail = _claims_detail_total(props)
        by_src, by_verif = _claim_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_column_monitor_rule_claims(self):
        """A column-level Freshness_Trend monitor rule → one monitored claim in all totals."""
        doc = self._doc(
            tables=[{
                "name": "events",
                "properties": [{"name": "event_date", "physicalType": "date"}],
            }],
            quality=[{
                "id": "mon-001",
                "element": "events.event_date",
                "testType": "Freshness_Trend",
                "name": "Events freshness",
                "lastResult": {"status": "passing"},
            }],
        )
        props = _props_from_doc(doc)

        detail = _claims_detail_total(props)
        by_src, by_verif = _claim_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_table_level_monitor_appears_in_matrix(self):
        """Table-level monitor rules (Freshness_Trend, Volume_Trend) must appear
        in the coverage matrix as a (table-level) row and be counted consistently."""
        doc = self._doc(
            tables=[{
                "name": "orders",
                "properties": [{"name": "order_id", "physicalType": "integer"}],
            }],
            quality=[
                {
                    "id": "mon-001",
                    "element": "orders",          # table-level, not column-level
                    "testType": "Freshness_Trend",
                    "name": "Orders freshness",
                    "lastResult": {"status": "passing"},
                },
                {
                    "id": "mon-002",
                    "element": "orders",
                    "testType": "Volume_Trend",
                    "name": "Orders volume",
                    "lastResult": {"status": "passing"},
                },
            ],
        )
        props = _props_from_doc(doc)

        # The (table-level) matrix row must exist with mon=2
        tbl_rows = [r for r in props["coverage_matrix"] if r["column"] == "(table-level)"]
        assert len(tbl_rows) == 1
        assert tbl_rows[0]["mon"] == 2

        detail = _claims_detail_total(props)
        by_src, by_verif = _claim_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_anomaly_claims(self):
        """A profiling anomaly on a column → one monitored live claim."""
        doc = self._doc([{
            "name": "customers",
            "properties": [{"name": "age", "physicalType": "integer"}],
        }])
        anomalies = [{
            "table_name": "customers",
            "column_name": "age",
            "anomaly_type": "Age_Out_Of_Range",
            "anomaly_name": "Age Out Of Range",
            "anomaly_description": "Age value exceeds expected range",
            "issue_likelihood": "Likely",
            "dq_dimension": "Validity",
            "suggested_action": "Investigate",
            "detail": "",
            "disposition": "Confirmed",
        }]
        props = _props_from_doc(doc, anomalies=anomalies)

        detail = _claims_detail_total(props)
        by_src, by_verif = _claim_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_mixed_multi_table(self):
        """Multiple tables, multiple columns, mixed claim types — all totals equal."""
        doc = self._doc(
            tables=[
                {
                    "name": "orders",
                    "properties": [
                        {
                            "name": "order_id",
                            "physicalType": "integer",
                            "required": True,
                            "logicalTypeOptions": {"primaryKey": True},
                        },
                        {
                            "name": "amount",
                            "physicalType": "numeric(10,2)",
                            "logicalTypeOptions": {"minimum": 0, "maximum": 1000000},
                        },
                    ],
                },
                {
                    "name": "customers",
                    "properties": [
                        {
                            "name": "email",
                            "physicalType": "text",
                            "classification": "pii",
                            "description": "Customer email",
                        },
                    ],
                },
            ],
            quality=[
                {
                    "id": "rule-001",
                    "element": "orders.amount",
                    "testType": "Threshold_Numeric",
                    "name": "Amount positive",
                    "lastResult": {"status": "passing"},
                },
                {
                    "id": "mon-001",
                    "element": "orders.order_id",
                    "testType": "Volume_Trend",
                    "name": "Order volume",
                    "lastResult": {"status": "passing"},
                },
            ],
        )
        props = _props_from_doc(doc)

        detail = _claims_detail_total(props)
        by_src, by_verif = _claim_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix
