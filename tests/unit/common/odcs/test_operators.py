import json
from importlib import resources

import pytest
import yaml

from testgen.common.enums import OdcsDimension, QualityDimension
from testgen.common.odcs.quality_rules import ACCEPTANCE_OPERATOR, Operator, bound_clause, odcs_dimension
from testgen.common.read_file import get_template_files

pytestmark = pytest.mark.unit


def _schema() -> dict:
    return json.loads(
        resources.files("testgen.common.odcs.schemas").joinpath("odcs-json-schema-v3.2.0.json").read_text()
    )


def _catalogue_operators() -> set[str]:
    operators: set[str] = set()
    for entry in get_template_files(r"test_types_.*\.yaml", sub_directory="dbsetup_test_types"):
        with entry.open("r") as f:
            doc = yaml.safe_load(f)
        for condition in doc["test_types"]["cat_test_conditions"]:
            operators.add(condition["test_operator"])
    assert operators, "parsed no operators from the test type catalogue"
    return operators


def test_the_operator_enum_matches_the_schema():
    # Set difference must be empty in both directions -- otherwise the enum is a second,
    # hand-maintained copy of the schema's vocabulary with nothing keeping the two honest.
    schema_values = {branch["required"][0] for branch in _schema()["$defs"]["DataQualityOperators"]["oneOf"]}
    code_values = {member.value for member in Operator}
    assert code_values == schema_values


@pytest.mark.parametrize("failure_operator, acceptance", [
    (">", Operator.MUST_BE_LESS_OR_EQUAL_TO),
    ("<", Operator.MUST_BE_GREATER_OR_EQUAL_TO),
    (">=", Operator.MUST_BE_LESS_THAN),
    ("NOT BETWEEN", Operator.MUST_BE_BETWEEN),
    ("<>", Operator.MUST_BE),
    ("!=", Operator.MUST_BE),
])
def test_a_failure_condition_inverts_into_an_acceptance_operator(failure_operator, acceptance):
    assert ACCEPTANCE_OPERATOR[failure_operator] is acceptance


def test_every_operator_the_catalogue_uses_has_an_inversion():
    # cat_test_conditions is nested under test_types: in each YAML -- a parser reading the
    # top level finds nothing, in every file, so this asserts the parse is non-empty first.
    assert not _catalogue_operators() - set(ACCEPTANCE_OPERATOR)


def test_two_distinct_bounds_render_one_between():
    assert bound_clause(10, 20) == {"mustBeBetween": [10, 20]}


def test_two_equal_bounds_render_must_be():
    assert bound_clause(100, 100) == {"mustBe": 100}


def test_one_bound_renders_the_matching_one_sided_operator():
    assert bound_clause(10, None) == {"mustBeGreaterOrEqualTo": 10}
    assert bound_clause(None, 20) == {"mustBeLessOrEqualTo": 20}


def test_no_bound_renders_nothing():
    assert bound_clause(None, None) == {}


def test_a_bound_clause_never_carries_two_operators():
    for lower, upper in [(1, 2), (1, 1), (1, None), (None, 2), (None, None)]:
        assert len(bound_clause(lower, upper)) <= 1


@pytest.mark.parametrize("lower, upper", [(10, 20), (100, 100), (10, None), (None, 20)])
def test_a_bound_clauses_keys_are_plain_strings_not_enum_members(lower, upper):
    # isinstance(key, str) is not enough -- an Operator member passes isinstance(key, str)
    # too, since StrEnum subclasses str. type(key) is str is the check that actually tells
    # a plain string apart from the enum member that yaml.safe_dump cannot represent.
    clause = bound_clause(lower, upper)
    assert all(type(key) is str for key in clause)


@pytest.mark.parametrize("lower, upper", [(10, 20), (100, 100), (10, None), (None, 20)])
def test_a_rule_built_from_a_bound_clause_survives_yaml_serialization(lower, upper):
    rule = {"metric": "nullValues", **bound_clause(lower, upper)}
    yaml.safe_dump(rule)


def test_validity_and_recency_are_translated_and_the_rest_pass_through_lower_cased():
    assert odcs_dimension(QualityDimension.VALIDITY) == "conformity"
    assert odcs_dimension(QualityDimension.RECENCY) == "timeliness"


def test_every_quality_dimension_translates_to_a_value_in_the_odcs_enum():
    # Derived from the enum, so a dimension added later fails here rather than rendering an
    # out-of-enum value into a customer's contract.
    for dimension in QualityDimension:
        assert odcs_dimension(dimension) in OdcsDimension


def test_odcs_dimension_returns_a_plain_string_not_an_enum_member():
    for dimension in QualityDimension:
        assert type(odcs_dimension(dimension)) is str


def test_a_dimension_value_survives_yaml_serialization():
    for dimension in QualityDimension:
        yaml.safe_dump({"dimension": odcs_dimension(dimension)})
