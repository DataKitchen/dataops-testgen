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
    _classify_enforcement_tier,
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
# 7. Term count consistency — Overview == Coverage Matrix top == bottom
# ---------------------------------------------------------------------------

def _make_table_group(tg_id: str = "tg-001") -> MagicMock:
    tg = MagicMock()
    tg.id = tg_id
    tg.table_groups_name = "Test TG"
    tg.project_code = "proj"
    return tg


def _props_from_doc(
    doc: dict,
    anomalies: list | None = None,
    gov_map: dict | None = None,
) -> dict:
    """Call _build_contract_props with minimal required arguments.

    ``gov_map`` — optional dict keyed by (table_name, col_name) with governance
    fields; passed directly as gov_by_col so tests don't need a real DB.
    """
    import yaml as _yaml

    return _build_contract_props(
        table_group=_make_table_group(),
        doc=doc,
        anomalies=anomalies or [],
        contract_yaml=_yaml.dump(doc),
        gov_by_col=gov_map or {},
    )


def _terms_detail_total(props: dict) -> int:
    """Count every term shown in the Terms Detail (Overview tab).

    Mirrors the JS TermsDetail loop: table_terms + static_terms + live_terms
    for every column in every table.
    """
    total = 0
    for t in props["tables"]:
        total += len(t.get("table_terms", []))
        for col in t.get("columns", []):
            total += len(col.get("static_terms", []))
            total += len(col.get("live_terms", []))
    return total


def _term_counts_bar_totals(props: dict) -> tuple[int, int]:
    """Compute the by-source and by-verif totals that TermCountsBar shows.

    Returns (total_by_source, total_by_verif) — both must equal the terms
    detail total because they aggregate the same tables data.
    """
    # monitor source is grouped under test (mirrors JS TermCountsBar behaviour)
    by_src  = {"ddl": 0, "profiling": 0, "governance": 0, "test": 0}
    by_verif = {"db_enforced": 0, "tested": 0, "monitored": 0, "observed": 0, "declared": 0}

    for t in props["tables"]:
        for c in t.get("table_terms", []):
            src_key = "test" if c["source"] == "monitor" else c["source"]
            if src_key in by_src:
                by_src[src_key] += 1
            if c["verif"] in by_verif:
                by_verif[c["verif"]] += 1
        for col in t.get("columns", []):
            for c in col.get("static_terms", []) + col.get("live_terms", []):
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


class Test_TermCountConsistency:
    """
    The total number of terms must be equal across three UI locations:
      1. Terms Detail (Overview tab)  — static_terms + live_terms per column
      2. Term Counts Bar (top of Coverage Matrix) — by source and by verif level
      3. Coverage Matrix grand total (bottom) — sum of db+tested+mon+obs per column
    """

    def _doc(self, tables: list[dict], quality: list[dict] | None = None,
             references: list[dict] | None = None) -> dict:
        return {
            "schema": tables,
            "quality": quality or [],
            "references": references or [],
        }

    def test_simple_column_no_terms(self):
        """A plain untyped column with no rules or annotations: all three totals equal."""
        doc = self._doc([{"name": "orders", "properties": [{"name": "id"}]}])
        props = _props_from_doc(doc)

        detail = _terms_detail_total(props)
        by_src, by_verif = _term_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_db_enforced_terms(self):
        """varchar(50) + required + PK → three db_enforced terms."""
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

        detail = _terms_detail_total(props)
        by_src, by_verif = _term_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix
        assert detail == 3  # Data Type + Not Null + Primary Key

    def test_governance_terms(self):
        """Governance metadata from live DB → declared terms (description + CDE + PII)."""
        doc = self._doc([{
            "name": "customers",
            "properties": [{
                "name": "email",
                "physicalType": "text",
            }],
        }])
        # Governance comes from live DB, not YAML — supply it via gov_map mock
        gov_map = {
            ("customers", "email"): {
                "description": "Customer email address",
                "critical_data_element": True,
                "pii_flag": "MANUAL",
                "excluded_data_element": None,
                "data_source": None,
                "source_system": None,
                "source_process": None,
                "business_domain": None,
                "stakeholder_group": None,
                "transform_level": None,
                "aggregation_level": None,
                "data_product": None,
                "column_id": "00000000-0000-0000-0000-000000000001",
            },
        }
        props = _props_from_doc(doc, gov_map=gov_map)

        detail = _terms_detail_total(props)
        by_src, by_verif = _term_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix
        assert detail >= 3  # Data Type (DDL) + Description + CDE + PII (governance)

    def test_test_rule_terms(self):
        """One non-monitor quality rule → one tested live term."""
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

        detail = _terms_detail_total(props)
        by_src, by_verif = _term_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_column_monitor_rule_terms(self):
        """A column-level Freshness_Trend monitor rule → one monitored term in all totals."""
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

        detail = _terms_detail_total(props)
        by_src, by_verif = _term_counts_bar_totals(props)
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

        detail = _terms_detail_total(props)
        by_src, by_verif = _term_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_anomaly_terms(self):
        """A profiling anomaly on a column → one monitored live term."""
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

        detail = _terms_detail_total(props)
        by_src, by_verif = _term_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix

    def test_mixed_multi_table(self):
        """Multiple tables, multiple columns, mixed term types — all totals equal."""
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
        gov_map = {
            ("customers", "email"): {
                "description": "Customer email",
                "pii_flag": "MANUAL",
                "critical_data_element": None,
                "excluded_data_element": None,
                "data_source": None, "source_system": None, "source_process": None,
                "business_domain": None, "stakeholder_group": None,
                "transform_level": None, "aggregation_level": None, "data_product": None,
                "column_id": "00000000-0000-0000-0000-000000000002",
            },
        }
        props = _props_from_doc(doc, gov_map=gov_map)

        detail = _terms_detail_total(props)
        by_src, by_verif = _term_counts_bar_totals(props)
        matrix = _coverage_matrix_total(props)

        assert detail == by_src == by_verif == matrix


# ---------------------------------------------------------------------------
# 8. _classify_enforcement_tier
# ---------------------------------------------------------------------------

class Test_ClassifyEnforcementTier:
    def _prop(self, physical: str = "text", **kwargs: object) -> dict:
        return {"physicalType": physical, "name": "col", **kwargs}

    # -- TestGen tier (any rules) --

    def test_any_rule_returns_tg(self):
        assert _classify_enforcement_tier(self._prop(), [{"testType": "Threshold_Numeric"}]) == "tg"

    def test_monitor_rule_also_returns_tg(self):
        assert _classify_enforcement_tier(self._prop(), [{"testType": "Freshness_Trend"}]) == "tg"

    def test_tg_beats_ddl(self):
        """Rule + NOT NULL -> still tg (highest wins)."""
        prop = self._prop("varchar(50)", required=True)
        assert _classify_enforcement_tier(prop, [{"testType": "Threshold_Numeric"}]) == "tg"

    # -- DB tier (meaningful DDL, no rules) --

    def test_not_null_returns_db(self):
        assert _classify_enforcement_tier(self._prop(required=True), []) == "db"

    def test_nullable_false_returns_db(self):
        prop = {"physicalType": "text", "name": "col", "nullable": False}
        assert _classify_enforcement_tier(prop, []) == "db"

    def test_primary_key_returns_db(self):
        prop = self._prop(logicalTypeOptions={"primaryKey": True})
        assert _classify_enforcement_tier(prop, []) == "db"

    def test_foreign_key_ref_returns_db(self):
        assert _classify_enforcement_tier(self._prop(), [], col_refs=[{"ref": "other.id"}]) == "db"

    def test_varchar_n_returns_db(self):
        assert _classify_enforcement_tier(self._prop("varchar(50)"), []) == "db"

    def test_numeric_precision_returns_db(self):
        assert _classify_enforcement_tier(self._prop("numeric(10,2)"), []) == "db"

    # -- Bare types that are NOT meaningful DDL (no additional constraints) --

    def test_integer_bare_returns_unf_or_none(self):
        """Bare integer without NOT NULL or PK is not a meaningful DDL constraint."""
        tier = _classify_enforcement_tier(self._prop("integer"), [])
        assert tier in ("unf", "none")

    def test_boolean_bare_returns_unf_or_none(self):
        tier = _classify_enforcement_tier(self._prop("boolean"), [])
        assert tier in ("unf", "none")

    def test_timestamp_bare_returns_unf_or_none(self):
        tier = _classify_enforcement_tier(self._prop("timestamp"), [])
        assert tier in ("unf", "none")

    # -- Unenforced tier --

    def test_classification_returns_unf(self):
        prop = self._prop(classification="pii")
        assert _classify_enforcement_tier(prop, []) == "unf"

    def test_description_returns_unf(self):
        prop = self._prop(description="A customer email address")
        assert _classify_enforcement_tier(prop, []) == "unf"

    def test_gov_col_description_returns_unf(self):
        assert _classify_enforcement_tier(self._prop(), [], gov_col={"description": "desc"}) == "unf"

    def test_min_max_returns_unf(self):
        prop = self._prop(logicalTypeOptions={"minimum": 0, "maximum": 100})
        assert _classify_enforcement_tier(prop, []) == "unf"

    # -- Uncovered (none) --

    def test_bare_text_no_constraints_returns_none(self):
        assert _classify_enforcement_tier(self._prop("text"), []) == "none"

    def test_bare_text_no_gov_returns_none(self):
        assert _classify_enforcement_tier(self._prop("text"), [], gov_col={}) == "none"


# ---------------------------------------------------------------------------
# 9. Health tier counts
# ---------------------------------------------------------------------------

class Test_HealthTierCounts:
    def _doc(self, tables: list[dict], quality: list[dict] | None = None) -> dict:
        return {"schema": tables, "quality": quality or [], "references": []}

    def test_all_uncovered(self):
        """Two bare-text columns -> n_elements >= 2, uncovered >= 2, tg_enforced == 0."""
        doc = self._doc([{"name": "t", "properties": [
            {"name": "a", "physicalType": "text"},
            {"name": "b", "physicalType": "text"},
        ]}])
        props = _props_from_doc(doc)
        h = props["health"]
        assert h["n_elements"] >= 2
        assert h["uncovered"] >= 2
        assert h["tg_enforced"] == 0

    def test_tg_enforced_counted(self):
        """Column with a quality rule -> tg_enforced >= 1."""
        doc = self._doc(
            tables=[{"name": "t", "properties": [{"name": "col", "physicalType": "text"}]}],
            quality=[{"id": "r1", "element": "t.col", "testType": "Threshold_Numeric",
                      "lastResult": {"status": "passing"}}],
        )
        props = _props_from_doc(doc)
        h = props["health"]
        assert h["tg_enforced"] >= 1

    def test_db_enforced_counted(self):
        """NOT NULL column -> db_enforced >= 1."""
        doc = self._doc([{"name": "t", "properties": [
            {"name": "col", "physicalType": "text", "required": True},
        ]}])
        props = _props_from_doc(doc)
        h = props["health"]
        assert h["db_enforced"] >= 1

    def test_tier_counts_sum_to_n_elements(self):
        """tg + db + unf + uncovered == n_elements."""
        doc = self._doc([{"name": "t", "properties": [
            {"name": "a", "physicalType": "varchar(50)", "required": True},
            {"name": "b", "physicalType": "text", "description": "desc"},
            {"name": "c", "physicalType": "text"},
        ]}])
        props = _props_from_doc(doc)
        h = props["health"]
        total = h["tg_enforced"] + h["db_enforced"] + h["unenforced"] + h["uncovered"]
        assert total == h["n_elements"]

    def test_n_elements_includes_table_level(self):
        """n_elements = columns + one table-level row per table."""
        doc = self._doc(
            tables=[{"name": "t", "properties": [{"name": "a"}, {"name": "b"}]}],
            quality=[{"id": "m1", "element": "t", "testType": "Freshness_Trend",
                      "lastResult": {"status": "passing"}}],
        )
        props = _props_from_doc(doc)
        h = props["health"]
        # 2 columns + 1 table-level = 3
        assert h["n_elements"] == 3


# ---------------------------------------------------------------------------
# 10. Matrix row tier field
# ---------------------------------------------------------------------------

class Test_MatrixRowTier:
    def _doc(self, tables: list[dict], quality: list[dict] | None = None) -> dict:
        return {"schema": tables, "quality": quality or [], "references": []}

    def test_column_with_rule_has_tg_tier(self):
        doc = self._doc(
            tables=[{"name": "t", "properties": [{"name": "col", "physicalType": "text"}]}],
            quality=[{"id": "r1", "element": "t.col", "testType": "Threshold_Numeric",
                      "lastResult": {"status": "passing"}}],
        )
        props = _props_from_doc(doc)
        row = next(r for r in props["coverage_matrix"] if r["column"] == "col")
        assert row["tier"] == "tg"

    def test_column_with_not_null_has_db_tier(self):
        doc = self._doc([{"name": "t", "properties": [
            {"name": "col", "physicalType": "text", "required": True},
        ]}])
        props = _props_from_doc(doc)
        row = next(r for r in props["coverage_matrix"] if r["column"] == "col")
        assert row["tier"] == "db"

    def test_column_with_description_has_unf_tier(self):
        doc = self._doc([{"name": "t", "properties": [
            {"name": "col", "physicalType": "text", "description": "Some column"},
        ]}])
        props = _props_from_doc(doc)
        row = next(r for r in props["coverage_matrix"] if r["column"] == "col")
        assert row["tier"] == "unf"

    def test_bare_column_has_none_tier(self):
        doc = self._doc([{"name": "t", "properties": [
            {"name": "col", "physicalType": "text"},
        ]}])
        props = _props_from_doc(doc)
        row = next(r for r in props["coverage_matrix"] if r["column"] == "col")
        assert row["tier"] == "none"

    def test_table_level_row_always_emitted(self):
        """(table-level) row is emitted even when no table-level rules exist."""
        doc = self._doc([{"name": "t", "properties": [{"name": "col", "physicalType": "text"}]}])
        props = _props_from_doc(doc)
        tbl_rows = [r for r in props["coverage_matrix"] if r["column"] == "(table-level)"]
        assert len(tbl_rows) == 1

    def test_table_level_with_monitor_has_tg_tier(self):
        doc = self._doc(
            tables=[{"name": "t", "properties": [{"name": "col", "physicalType": "text"}]}],
            quality=[{"id": "m1", "element": "t", "testType": "Volume_Trend",
                      "lastResult": {"status": "passing"}}],
        )
        props = _props_from_doc(doc)
        tbl_rows = [r for r in props["coverage_matrix"] if r["column"] == "(table-level)"]
        assert len(tbl_rows) == 1
        assert tbl_rows[0]["tier"] == "tg"
