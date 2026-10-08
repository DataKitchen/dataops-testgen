import re
from types import SimpleNamespace

import pytest
import yaml

from testgen.common.odcs.quality_rules import (
    _INEXACT_FAMILIES,
    _LIBRARY_ROWS,
    CUSTOM_ROUTING_REASONS,
    DECLARATION_TEST_TYPES,
    EMAIL_PATTERN,
    EXCLUDED_TEST_TYPES,
    RULE_MAPPINGS,
    US_STATE_VALID_VALUES,
    US_ZIP3_PATTERN,
    US_ZIP_PATTERN,
    RuleScope,
    RuleShape,
    rule_scope,
    rule_shape,
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


def test_every_exclusion_carries_a_reason():
    assert all(reason.strip() for reason in EXCLUDED_TEST_TYPES.values())


def test_only_run_history_types_are_excluded():
    assert set(EXCLUDED_TEST_TYPES) == {
        "Volume_Trend", "Freshness_Trend", "Metric_Trend", "Schema_Drift",
    }


def test_the_mapping_names_no_test_type_the_catalogue_does_not_have():
    assert not set(RULE_MAPPINGS) - _catalogue_test_types()


def test_the_exclusions_name_no_test_type_the_catalogue_does_not_have():
    assert not set(EXCLUDED_TEST_TYPES) - _catalogue_test_types()


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


def test_every_catalogue_type_routes_to_exactly_one_shape():
    for test_type in _catalogue_test_types():
        shape = rule_shape(test_type)
        if test_type in EXCLUDED_TEST_TYPES:
            assert shape is None, f"{test_type} is excluded but routes to {shape}"
        else:
            assert shape in (RuleShape.LIBRARY, RuleShape.SQL, RuleShape.CUSTOM), (
                f"{test_type} routes to {shape!r}"
            )


def test_a_type_outside_the_catalogue_falls_through_to_custom():
    """The fallthrough is what makes a new test type export with no mapping change. An
    unknown name is not an error here -- `rule_scope` is where a term TestGen should not
    be holding gets refused.
    """
    assert rule_shape("No_Such_Test_Type") is RuleShape.CUSTOM


def test_the_library_table_holds_exactly_the_decided_types():
    assert set(_LIBRARY_ROWS) == {
        "Required", "Missing_Pct", "Row_Ct", "Row_Ct_Pct",
        "Dupe_Rows", "LOV_Match", "Pattern_Match",
        "Required_No_Placeholder", "Email_Format", "Valid_US_Zip", "Valid_US_Zip3", "US_State", "Constant",
        "Match_Row_Ct", "Match_Null_Ct",
    }


def test_sql_metric_is_the_only_sql_row():
    assert {test_type for test_type, mapping in RULE_MAPPINGS.items() if mapping.shape is RuleShape.SQL} == {
        "SQL_Metric"
    }


def test_the_declaration_types_are_the_decided_six():
    assert DECLARATION_TEST_TYPES == {"Min_Val", "Max_Val", "Min_Date", "Max_Date", "Text_Length_Range", "Unique"}


def test_every_custom_routing_reason_names_a_custom_catalogue_type():
    catalogue = _catalogue_test_types()
    for test_type, reason in CUSTOM_ROUTING_REASONS.items():
        assert reason.strip(), f"{test_type} carries no reason"
        assert test_type in catalogue, f"{test_type} is not in the catalogue"
        assert rule_shape(test_type) is RuleShape.CUSTOM, f"{test_type} has a reason to stay custom but is routed"
        assert test_type not in DECLARATION_TEST_TYPES


def _postgresql_measure(test_type: str) -> str:
    conditions = _catalogue_entries()[test_type]["cat_test_conditions"]
    return next(condition["measure"] for condition in conditions if condition["sql_flavor"] == "postgresql")


def test_the_fixed_email_pattern_is_the_one_the_measure_checks():
    # The measure writes the apostrophe doubled, as a SQL string literal must.
    assert f"!~ '{EMAIL_PATTERN.replace(chr(39), chr(39) * 2)}'" in _postgresql_measure("Email_Format")


def test_the_fixed_state_list_is_the_one_the_measure_checks():
    measure = _postgresql_measure("US_State")
    listed = re.search(r"NOT IN \(([^)]*)\)", measure).group(1)
    assert [code.strip().strip("'") for code in listed.split(",")] + [""] == list(US_STATE_VALID_VALUES)
    assert "NULLIF({COLUMN_NAME}, '')" in measure, "the empty string is only valid while the measure excludes it"


@pytest.mark.parametrize(("test_type", "pattern", "valid", "invalid"), [
    ("Valid_US_Zip", US_ZIP_PATTERN, ["02139", "021391234", "02139-1234"], ["", "0213", "0213X", "02139-12"]),
    ("Valid_US_Zip3", US_ZIP3_PATTERN, ["021"], ["", "02", "0213", "02X"]),
])
def test_a_fixed_zip_pattern_accepts_exactly_the_shapes_the_measure_accepts(test_type, pattern, valid, invalid):
    """The measure maps every digit to 9 and compares the result against fixed shapes."""
    measure = _postgresql_measure(test_type)
    shapes = re.findall(r"'(9[9-]*)'", measure.split("'999999999')", 1)[-1])
    for value in [*valid, *invalid]:
        translated = value.translate(str.maketrans("012345678", "999999999"))
        assert (re.search(pattern, value) is not None) == (translated in shapes), value


@pytest.mark.parametrize("test_type", [
    "Table_Freshness", "Unique_Pct",
    "Aggregate_Balance", "Aggregate_Balance_Percent", "Aggregate_Balance_Range",
    "Aggregate_Minimum", "Combo_Match", "Distribution_Shift",
    "Timeframe_Combo_Gain", "Timeframe_Combo_Match", "CUSTOM",
])
def test_the_formerly_deferred_types_route_to_custom(test_type):
    assert rule_shape(test_type) is RuleShape.CUSTOM


def test_dupe_rows_routes_to_the_library_table():
    assert rule_shape("Dupe_Rows") is RuleShape.LIBRARY


def _test_type_stub(entry: dict) -> SimpleNamespace:
    return SimpleNamespace(
        test_type=entry["test_type"],
        test_scope=entry["test_scope"],
        column_name_prompt=entry.get("column_name_prompt"),
        default_parm_columns=entry.get("default_parm_columns"),
    )


def test_scope_is_derived_from_the_catalogue_not_declared():
    """A rule hangs on a property exactly when the term's `column_name` denotes one column
    (`test_scope: column`) or an aggregate over one (`column_name_prompt: Aggregate
    Expression`). Every other stored scope puts something in `column_name` that is not a
    column: a free-text label, a list of columns, or nothing.
    """
    for test_type, entry in _catalogue_entries().items():
        if test_type in EXCLUDED_TEST_TYPES or test_type == "Dupe_Rows":
            continue
        names_one_column = (
            entry["test_scope"] == "column"
            or (entry.get("column_name_prompt") or "").strip() == "Aggregate Expression"
        )
        expected = RuleScope.COLUMN if names_one_column else RuleScope.TABLE
        term = SimpleNamespace(test_type=test_type, groupby_names=None)
        assert rule_scope(term, _test_type_stub(entry)) is expected


@pytest.mark.parametrize("test_scope", ["column", "table"])
@pytest.mark.parametrize("groupby_names", ["a", "a,b", "a,b,c"])
def test_a_scope_that_does_not_follow_the_term_never_varies_with_it(groupby_names, test_scope):
    """Each type is run under both stored scopes, so a term-dependent branch that returns a constant
    differs from the catalogue-derived answer under one of the two."""
    entries = _catalogue_entries()
    for test_type, mapping in RULE_MAPPINGS.items():
        if mapping.scope_follows_term:
            continue
        stub = _test_type_stub({**entries[test_type], "test_scope": test_scope})
        baseline = rule_scope(SimpleNamespace(test_type=test_type, groupby_names=None), stub)
        term = SimpleNamespace(test_type=test_type, groupby_names=groupby_names)
        assert rule_scope(term, stub) is baseline, test_type


def test_an_excluded_type_is_refused_rather_than_placed():
    for test_type in EXCLUDED_TEST_TYPES:
        entry = _catalogue_entries()[test_type]
        term = SimpleNamespace(test_type=test_type, groupby_names=None)
        with pytest.raises(ValueError, match="no node to attach"):
            rule_scope(term, _test_type_stub(entry))


def test_a_fixed_pattern_is_exact_on_every_family_not_listed_as_inexact():
    """A family whose measure states the pattern renders the library rule; any other renders custom."""
    literal = f"'{EMAIL_PATTERN.replace(chr(39), chr(39) * 2)}'"
    for condition in _catalogue_entries()["Email_Format"]["cat_test_conditions"]:
        states_pattern = literal in condition["measure"]
        assert states_pattern != (condition["sql_flavor"] in _INEXACT_FAMILIES["Email_Format"]), condition["sql_flavor"]
