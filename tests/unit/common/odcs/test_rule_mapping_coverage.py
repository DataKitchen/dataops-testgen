import pytest
import yaml

from testgen.common.odcs.quality_rules import (
    EXCLUDED_TEST_TYPES,
    PENDING_DECISION,
    RULE_MAPPINGS,
    RuleScope,
    RuleShape,
    declared_scope,
)
from testgen.common.read_file import get_template_files

pytestmark = pytest.mark.unit


def _catalogue_entries() -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for entry in get_template_files(r"test_types_.*\.yaml", sub_directory="dbsetup_test_types"):
        with entry.open("r") as f:
            doc = yaml.safe_load(f)
        entries[doc["test_types"]["test_type"]] = doc["test_types"]
    assert entries, "parsed no test types from the test type catalogue"
    return entries


def _catalogue_test_types() -> set[str]:
    return set(_catalogue_entries())


def test_every_test_type_in_the_catalogue_is_routed_or_excluded():
    unrouted = _catalogue_test_types() - set(RULE_MAPPINGS) - set(EXCLUDED_TEST_TYPES) - set(PENDING_DECISION)
    assert not unrouted, f"no quality-rule mapping for: {sorted(unrouted)}"


def test_every_exclusion_carries_a_reason():
    assert all(reason.strip() for reason in EXCLUDED_TEST_TYPES.values())


def test_every_pending_decision_carries_a_reason():
    assert all(routing.reason.strip() for routing in PENDING_DECISION.values())


def test_every_pending_decision_carries_a_scope():
    """A type lands in ``PENDING_DECISION`` because its rule *shape* is undecided. Which node
    its rule hangs on is a separate question the renderer cannot defer -- it has to attach the
    rule somewhere -- so it is declared here rather than inferred from whether the term
    carries a ``column_name``, which on several of these types is a free-text label or a
    comma-separated list of columns rather than a column.
    """
    for test_type, routing in PENDING_DECISION.items():
        assert isinstance(routing.scope, RuleScope), f"{test_type} carries no rule scope"


def test_every_declared_scope_agrees_with_the_catalogue():
    """The catalogue already says where a rule belongs, in two fields: a rule hangs on a
    property exactly when the term's ``column_name`` denotes one column (``test_scope:
    column``) or an aggregate over one (``column_name_prompt: Aggregate Expression``). Every
    other stored scope -- ``table``, ``custom``, ``referential`` -- puts something in
    ``column_name`` that is not a column: a free-text label, a list of columns, or nothing.

    Deriving the expectation here rather than restating the declarations is what makes this
    catch a *new* test type, or a changed ``test_scope`` on an existing one, whose declared
    scope no longer matches what its own catalogue entry says the field holds.
    """
    for test_type, entry in _catalogue_entries().items():
        if test_type in EXCLUDED_TEST_TYPES:
            continue
        names_one_column = (
            entry["test_scope"] == "column"
            or (entry.get("column_name_prompt") or "").strip() == "Aggregate Expression"
        )
        expected = RuleScope.COLUMN if names_one_column else RuleScope.TABLE
        assert declared_scope(test_type) is expected, (
            f"{test_type} declares {declared_scope(test_type)}, but its catalogue entry "
            f"(test_scope={entry['test_scope']!r}, "
            f"column_name_prompt={(entry.get('column_name_prompt') or '').strip()!r}) says {expected}"
        )


def test_a_test_type_that_declares_no_scope_is_refused_rather_than_guessed():
    """``EXCLUDED_TEST_TYPES`` and anything outside the catalogue reach ``declared_scope``
    only through a term authored against a type no contract should hold one for. Refusing is
    what keeps placement declared everywhere: a fallback here would be the ``column_name``
    heuristic again, under a different name.
    """
    for test_type in (*EXCLUDED_TEST_TYPES, "No_Such_Test_Type"):
        with pytest.raises(ValueError, match="declares no rule scope"):
            declared_scope(test_type)


def test_only_run_history_types_are_excluded():
    assert set(EXCLUDED_TEST_TYPES) == {
        "Volume_Trend", "Freshness_Trend", "Metric_Trend", "Schema_Drift",
    }


def test_the_mapping_names_no_test_type_the_catalogue_does_not_have():
    assert not set(RULE_MAPPINGS) - _catalogue_test_types()


def test_the_exclusions_name_no_test_type_the_catalogue_does_not_have():
    assert not set(EXCLUDED_TEST_TYPES) - _catalogue_test_types()


def test_the_pending_decisions_name_no_test_type_the_catalogue_does_not_have():
    assert not set(PENDING_DECISION) - _catalogue_test_types()


def test_the_three_dicts_are_pairwise_disjoint():
    routed, excluded, pending = set(RULE_MAPPINGS), set(EXCLUDED_TEST_TYPES), set(PENDING_DECISION)
    assert not (routed & excluded), f"routed and excluded overlap: {sorted(routed & excluded)}"
    assert not (routed & pending), f"routed and pending overlap: {sorted(routed & pending)}"
    assert not (excluded & pending), f"excluded and pending overlap: {sorted(excluded & pending)}"


def test_a_library_row_carries_a_metric_and_a_scope_and_nothing_else_does():
    for test_type, mapping in RULE_MAPPINGS.items():
        assert mapping.scope is not None, f"{test_type} carries no scope"
        if mapping.shape is RuleShape.LIBRARY:
            assert mapping.metric is not None, f"{test_type} is a library row with no metric"
        else:
            assert mapping.metric is None, f"{test_type} is not a library row but carries a metric"


def test_every_row_carries_the_test_type_it_is_keyed_by():
    for test_type, mapping in RULE_MAPPINGS.items():
        assert mapping.test_type == test_type


def test_every_row_carries_an_operator():
    for test_type, mapping in RULE_MAPPINGS.items():
        assert mapping.operator is not None, f"{test_type} carries no operator"


def test_every_row_carries_a_dimension():
    for test_type, mapping in RULE_MAPPINGS.items():
        assert mapping.dimension, f"{test_type} carries no dimension"


# Deferred routings. Each of these fails today because the type has no row in RULE_MAPPINGS --
# that is the expected reason. `strict=True` means the marker itself starts failing CI the
# moment someone routes the type and forgets to remove it.


@pytest.mark.xfail(
    strict=True,
    reason="routing deferred: Unique's measure counts NULLs as duplicates, so no threshold "
    "conversion makes duplicateValues match it -- what metric or corrected measure applies?",
)
def test_unique_is_routed_once_the_null_counting_mismatch_is_resolved():
    mapping = RULE_MAPPINGS.get("Unique")
    assert mapping is not None
    assert mapping.shape in (RuleShape.LIBRARY, RuleShape.SQL)


@pytest.mark.xfail(
    strict=True,
    reason="routing deferred: Dupe_Rows has no threshold parameter, only an implicit bound -- "
    "what does the rendered rule's operator and value need to be?",
)
def test_dupe_rows_is_routed_once_its_implicit_bound_is_decided():
    mapping = RULE_MAPPINGS.get("Dupe_Rows")
    assert mapping is not None
    assert mapping.shape in (RuleShape.LIBRARY, RuleShape.SQL)


@pytest.mark.xfail(
    strict=True,
    reason="routing deferred: Table_Freshness has no scalar measure and no numeric threshold -- "
    "its bound is a fingerprint comparison, so what the rendered rule should assert is undecided.",
)
def test_table_freshness_is_routed_once_its_fingerprint_bound_is_decided():
    mapping = RULE_MAPPINGS.get("Table_Freshness")
    assert mapping is not None
    assert mapping.shape in (RuleShape.LIBRARY, RuleShape.SQL)


@pytest.mark.xfail(
    strict=True,
    reason="routing deferred: this type has no scalar cat_test_conditions measure -- does it "
    "render sql (a wrapped join query) or custom (an engine/implementation block)?",
)
@pytest.mark.parametrize("test_type", [
    "Aggregate_Balance",
    "Aggregate_Balance_Percent",
    "Aggregate_Balance_Range",
    "Aggregate_Minimum",
    "Combo_Match",
    "Distribution_Shift",
    "Timeframe_Combo_Gain",
    "Timeframe_Combo_Match",
    "CUSTOM",
])
def test_a_no_scalar_type_is_routed_once_sql_vs_custom_is_decided(test_type):
    mapping = RULE_MAPPINGS.get(test_type)
    assert mapping is not None
    assert mapping.shape in (RuleShape.SQL, RuleShape.CUSTOM)
