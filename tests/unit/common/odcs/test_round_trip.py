"""A term rendered into an ODCS document resolves back to the same test type, identity and parameters."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml

from testgen.common.clean_sql import parse_value_list
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.common.odcs import render
from testgen.common.odcs.quality_rules import (
    DECLARATION_TEST_TYPES,
    EXCLUDED_TEST_TYPES,
    RULE_MAPPINGS,
    ResolvedTerm,
    RuleScope,
    _groupby_columns,
    lov_values,
    resolve_declarations,
    resolve_rule,
)
from testgen.common.odcs.render import render_document
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND, ServerType
from testgen.common.odcs.validation import validate_document
from testgen.common.read_file import get_template_files

pytestmark = pytest.mark.unit


def _catalogue() -> dict[str, dict]:
    entries = {}
    for entry in get_template_files(r"test_types_.*\.yaml", sub_directory="dbsetup_test_types"):
        with entry.open("r") as f:
            doc = yaml.safe_load(f)["test_types"]
        entries[doc["test_type"]] = doc
    return entries


_CATALOGUE = _catalogue()


def _test_type(code: str) -> TestType:
    entry = _CATALOGUE[code]
    return TestType(
        test_type=code,
        test_scope=entry["test_scope"],
        dq_dimension=entry["dq_dimension"],
        default_parm_columns=entry.get("default_parm_columns"),
        column_name_prompt=entry.get("column_name_prompt"),
        test_name_short=entry.get("test_name_short"),
        test_name_long=entry.get("test_name_long"),
        test_description=entry.get("test_description"),
        except_message=entry.get("except_message"),
        threshold_description=entry.get("threshold_description"),
    )


_METADATA = {"odcs": {"name": "Agreed check", "tags": ["finance"], "businessImpact": "operational"}, "owner": "ops"}

# Every routed and declared type, plus the variants that fall back to custom (a tolerant bound, a date Constant,
# a cleared threshold or baseline) or declare one bound; each term sits on its own column so no two declare the same field.
# (test type, column, column logicalType, term fields)
_TERMS: list[tuple[str, str | None, str | None, dict]] = [
    ("Required", "c_required", "string", {"threshold_value": "3"}),
    ("Missing_Pct", "c_missing", "number",
     {"baseline_ct": "1000", "baseline_value_ct": "950", "threshold_value": "0.05"}),
    ("Row_Ct", None, None, {"threshold_value": "100"}),
    ("Dupe_Rows", "c_dupe", "string", {"groupby_names": '"c_dupe"', "skip_errors": 2}),
    ("LOV_Match", "c_lov", "string", {"baseline_value": "('Y','N','it''s')", "threshold_value": "0"}),
    ("Pattern_Match", "c_pattern", "string", {"baseline_value": "[A-Z]{3}", "threshold_value": "1"}),
    ("Required_No_Placeholder", "c_rnp", "string", {"baseline_value": '"",N/A,"a,b"', "threshold_value": "0"}),
    ("Email_Format", "c_email", "string", {"threshold_value": "2"}),
    ("Valid_US_Zip", "c_zip", "string", {"threshold_value": "2"}),
    ("Valid_US_Zip3", "c_zip3", "string", {"threshold_value": "2"}),
    ("US_State", "c_state", "string", {"threshold_value": "2"}),
    ("Constant", "c_constant", "string", {"baseline_value": "'it''s'", "threshold_value": "0"}),
    ("Constant", "c_constant_date", "date", {"baseline_value": "'2026-01-01'", "threshold_value": "0"}),
    ("Match_Null_Ct", "c_nulls", "number", {"baseline_ct": "12"}),
    ("Match_Null_Ct", "c_nulls_unset", "number", {}),
    ("Required", "c_required_unset", "string", {}),
    ("Min_Val", "c_min", "number", {"baseline_value": "-5.5", "threshold_value": "0"}),
    ("Max_Val", "c_max", "integer", {"baseline_value": "100", "threshold_value": "0", "custom_metadata": _METADATA}),
    ("Max_Val", "c_max_tolerant", "integer", {"baseline_value": "100", "threshold_value": "2"}),
    ("Min_Date", "c_min_date", "date", {"baseline_value": "2026-01-01", "threshold_value": "0"}),
    ("Max_Date", "c_max_date", "timestamp", {"baseline_value": "2026-01-31 06:00:00", "threshold_value": "0"}),
    ("Text_Length_Range", "c_length", "string",
     {"lower_tolerance": "2", "upper_tolerance": "9", "threshold_value": "0"}),
    ("Text_Length_Range", "c_max_length", "string", {"upper_tolerance": "9", "threshold_value": "0"}),
    ("Unique", "c_unique", "integer", {"threshold_value": "0"}),
    ("Avg_Shift", "c_avg", "number", {"baseline_value_ct": "10", "baseline_avg": "4.2", "baseline_sd": "1.1",
                                      "threshold_value": "2", "custom_metadata": _METADATA}),
]
# Table-scoped terms, which share the table's quality list.
_TABLE_TERMS: list[tuple[str, dict]] = [
    ("Row_Ct_Pct", {"baseline_ct": "1000", "threshold_value": "10"}),
    ("Match_Row_Ct", {"threshold_value": "600"}),
    ("Dupe_Rows", {"groupby_names": '"c_required", "c_lov"', "skip_errors": 0}),
    ("SQL_Metric", {"custom_query": "SELECT COUNT(*) AS late FROM {DATA_SCHEMA}.orders;", "lower_tolerance": "1",
                    "upper_tolerance": "10"}),
    ("SQL_Metric", {"custom_query": "SELECT 1", "upper_tolerance": "5"}),
    ("SQL_Metric", {"custom_query": "SELECT 2;", "upper_tolerance": "5"}),
    ("SQL_Metric", {"custom_query": "SELECT 3"}),
]


def _terms() -> list[TestDefinition]:
    terms = []
    for index, (code, column, _, fields) in enumerate(_TERMS):
        terms.append(TestDefinition(
            test_type=code, schema_name="sales", table_name="orders", column_name=column,
            contract_term_id=f"term-{index}-{code}", **fields,
        ))
    for index, (code, fields) in enumerate(_TABLE_TERMS):
        terms.append(TestDefinition(
            test_type=code, schema_name="sales", table_name="orders", column_name=None,
            contract_term_id=f"table-term-{index}-{code}", **fields,
        ))
    return terms


def _version() -> SuiteVersion:
    properties = [
        {"name": column, **({"logicalType": logical_type} if logical_type else {})}
        for _, column, logical_type, _ in _TERMS if column
    ]
    return SuiteVersion(
        id=uuid4(), test_suite_id=uuid4(), version=1, odcs_api_version=ODCS_API_VERSION,
        metadata_document={
            "apiVersion": ODCS_API_VERSION, "kind": ODCS_KIND, "id": "contract-1", "version": "1.0.0",
            "schema": [{"name": "orders", "properties": properties}],
        },
    )


def _render(terms: list[TestDefinition]) -> dict:
    test_types = {term.test_type: _test_type(term.test_type) for term in terms}
    with (
        patch.object(render, "_terms_for_version", return_value=terms),
        patch.object(render, "_test_types_for", return_value=test_types),
        patch.object(render, "_table_group_for", return_value=TableGroup(id=uuid4(), connection_id=1)),
        patch.object(render, "_flavor_code_for", return_value="postgresql"),
        patch.object(render, "_conditions_for", return_value={}),
        patch.object(render, "_column_types_for", return_value={}),
    ):
        return render_document(_version())


def _resolve(document: dict) -> dict[str, ResolvedTerm]:
    known = frozenset(_CATALOGUE)
    resolved: list[ResolvedTerm | None] = []
    for table in document["schema"]:
        resolved += [
            resolve_rule(rule, RuleScope.TABLE, known, server_type=ServerType.POSTGRES)
            for rule in table.get("quality", [])
        ]
        for prop in table.get("properties", []):
            resolved += [
                resolve_rule(rule, RuleScope.COLUMN, known, prop["name"], server_type=ServerType.POSTGRES)
                for rule in prop.get("quality", [])
            ]
            resolved += resolve_declarations(prop, known)
    assert None not in resolved, "a rendered rule did not resolve"
    by_id = {term.contract_term_id: term for term in resolved}
    assert len(by_id) == len(resolved), "two resolved terms share an id"
    return by_id


def _declared_parameters(term: TestDefinition) -> dict:
    """The term's values for the parameters its type declares, as ``test_definitions`` holds them."""
    names = [name.strip() for name in (_CATALOGUE[term.test_type].get("default_parm_columns") or "").split(",")]
    return {name: getattr(term, name) for name in names if getattr(term, name) not in (None, "")}


def _comparable(test_type: str, name: str, value: object) -> object:
    if name == "baseline_value" and test_type == "LOV_Match":
        return lov_values(value)
    if name == "baseline_value" and test_type == "Required_No_Placeholder":
        return parse_value_list(value)
    if name == "groupby_names":
        return _groupby_columns(SimpleNamespace(groupby_names=value))
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


@pytest.fixture(scope="module")
def round_trip() -> tuple[list[TestDefinition], dict, dict[str, ResolvedTerm]]:
    terms = _terms()
    document = _render(terms)
    return terms, document, _resolve(document)


def test_the_round_trip_covers_every_routed_and_declared_type(round_trip):
    terms, _, _ = round_trip
    assert {term.test_type for term in terms} >= set(RULE_MAPPINGS) | DECLARATION_TEST_TYPES
    assert not {term.test_type for term in terms} & set(EXCLUDED_TEST_TYPES)


def test_the_rendered_document_validates(round_trip):
    _, document, _ = round_trip
    assert validate_document(document) == []


def test_every_term_resolves_back_to_its_own_identity_and_type(round_trip):
    terms, _, resolved = round_trip
    assert set(resolved) == {term.contract_term_id for term in terms}
    for term in terms:
        assert resolved[term.contract_term_id].test_type == term.test_type, term.contract_term_id


def test_every_term_resolves_back_to_its_own_parameters(round_trip):
    terms, _, resolved = round_trip
    for term in terms:
        expected = _declared_parameters(term)
        got = resolved[term.contract_term_id].parameters
        assert set(got) == set(expected), f"{term.contract_term_id}: {sorted(got)} != {sorted(expected)}"
        for name, value in expected.items():
            assert _comparable(term.test_type, name, got[name]) == _comparable(term.test_type, name, value), (
                f"{term.contract_term_id}.{name}: {got[name]!r} != {value!r}"
            )


def test_a_declared_term_keeps_the_metadata_its_rule_would_carry(round_trip):
    """Max_Val and Avg_Shift carry the same metadata; one renders as a declaration and one as a rule."""
    terms, document, resolved = round_trip
    declared = next(term for term in terms if term.column_name == "c_max")
    ruled = next(term for term in terms if term.test_type == "Avg_Shift")
    assert not any(rule.get("id") == declared.contract_term_id for rule in _rules(document))

    declared_metadata = resolved[declared.contract_term_id].metadata
    ruled_metadata = resolved[ruled.contract_term_id].metadata
    for key in ("name", "tags", "businessImpact", "customProperties"):
        assert declared_metadata[key] == ruled_metadata[key], key


def test_a_stored_marker_is_replaced_not_duplicated():
    """A metadata document carrying an earlier render's marker must not resolve to the term twice."""
    terms = [TestDefinition(
        test_type="Unique", schema_name="sales", table_name="orders", column_name="c_unique",
        threshold_value="0", contract_term_id="term-unique",
    )]
    first = _render(terms)
    stored = _version()
    stored.metadata_document = first
    test_types = {"Unique": _test_type("Unique")}
    with (
        patch.object(render, "_terms_for_version", return_value=terms),
        patch.object(render, "_test_types_for", return_value=test_types),
        patch.object(render, "_table_group_for", return_value=TableGroup(id=uuid4(), connection_id=1)),
        patch.object(render, "_flavor_code_for", return_value="postgresql"),
        patch.object(render, "_conditions_for", return_value={}),
        patch.object(render, "_column_types_for", return_value={}),
    ):
        second = render_document(stored)

    assert [term.contract_term_id for term in _resolve(second).values()] == ["term-unique"]


def test_a_declaration_no_marker_names_resolves_to_nothing():
    prop = {"name": "amount", "logicalType": "number", "logicalTypeOptions": {"maximum": 10}, "unique": True}
    assert resolve_declarations(prop, frozenset(_CATALOGUE)) == []


@pytest.mark.parametrize("value", [
    {"id": "t", "testType": "Max_Val", "declares": ["logicalTypeOptions.minimum"]},
    {"id": "t", "testType": "Unique", "declares": ["unique"]},
    {"id": "t", "testType": "Avg_Shift", "declares": ["logicalTypeOptions.maximum"]},
    {"testType": "Max_Val", "declares": ["logicalTypeOptions.maximum"]},
    {"id": "t", "testType": "Max_Val", "declares": ["logicalTypeOptions.maximum", "unique"]},
])
def test_a_marker_that_does_not_match_its_declaration_resolves_to_nothing(value):
    prop = {
        "name": "amount", "logicalType": "number", "logicalTypeOptions": {"maximum": 10}, "unique": True,
        "customProperties": [{"property": "testgenTerm", "value": value, "vendor": "testgen"}],
    }
    assert resolve_declarations(prop, frozenset(_CATALOGUE)) == []


def _rules(document: dict) -> list[dict]:
    rules = []
    for table in document["schema"]:
        rules += table.get("quality", [])
        for prop in table.get("properties", []):
            rules += prop.get("quality", [])
    return rules


def _rendered_rule(code: str, column: str | None = "c_rule", **fields) -> dict:
    term = TestDefinition(
        test_type=code, schema_name="sales", table_name="orders", column_name=column,
        contract_term_id=f"term-{code}", **fields,
    )
    document = _render([term])
    return next(rule for rule in _rules(document) if rule["id"] == term.contract_term_id)


@pytest.mark.parametrize(("code", "fields", "edit"), [
    ("Email_Format", {"threshold_value": "0"}, {"pattern": "^x$"}),
    ("US_State", {"threshold_value": "0"}, {"validValues": ["CA"]}),
    ("Constant", {"baseline_value": "'x'", "threshold_value": "0"}, {"validValues": ["a", "b"]}),
    ("Constant", {"baseline_value": "'x'", "threshold_value": "0"}, {"validValues": [None]}),
    ("Required_No_Placeholder", {"baseline_value": "N/A", "threshold_value": "0"}, {"missingValues": "N/A"}),
])
def test_a_marked_rule_whose_argument_was_edited_is_declined(code, fields, edit):
    """The marker names the type, but the edited rule checks something else, so it is not that type's term."""
    rule = _rendered_rule(code, column="c_constant" if code == "Constant" else "c_rule", **fields)
    edited = {**rule, "arguments": edit}
    assert (
        resolve_rule(edited, RuleScope.COLUMN, frozenset(_CATALOGUE), "c_rule", server_type=ServerType.POSTGRES)
        is None
    )


@pytest.mark.parametrize("bound", [
    {"mustBeGreaterThan": 5}, {"mustBeBetween": [1]}, {"mustBeBetween": 5}, {"mustBeBetween": [1, 2, 3]},
])
def test_a_sql_metric_rule_with_a_bound_its_projection_never_writes_is_declined(bound):
    rule = _rendered_rule("SQL_Metric", column=None, custom_query="SELECT 1", lower_tolerance="1", upper_tolerance="5")
    edited = {key: value for key, value in rule.items() if not key.startswith("must")} | bound
    assert resolve_rule(edited, RuleScope.TABLE, frozenset(_CATALOGUE), server_type=ServerType.POSTGRES) is None


def test_an_unquoted_yaml_date_resolves_as_the_date_it_names():
    prop = {
        "name": "shipped", "logicalType": "date", "logicalTypeOptions": {"maximum": date(2026, 1, 31)},
        "customProperties": [{
            "property": "testgenTerm", "vendor": "testgen",
            "value": {"id": "t", "testType": "Max_Date", "declares": ["logicalTypeOptions.maximum"]},
        }],
    }
    (resolved,) = resolve_declarations(prop, frozenset(_CATALOGUE))
    assert resolved.parameters == {"baseline_value": "2026-01-31", "threshold_value": "0"}


def test_a_stored_declaration_goes_with_its_marker():
    """Rendered output stored as metadata must not keep enforcing a bound its term no longer declares."""
    declared = TestDefinition(
        test_type="Max_Val", schema_name="sales", table_name="orders", column_name="c_max",
        baseline_value="100", threshold_value="0", contract_term_id="term-max",
    )
    stored = _version()
    stored.metadata_document = _render([declared])

    tolerant = TestDefinition(
        test_type="Max_Val", schema_name="sales", table_name="orders", column_name="c_max",
        baseline_value="100", threshold_value="2", contract_term_id="term-max",
    )
    for terms in ([tolerant], []):
        with (
            patch.object(render, "_terms_for_version", return_value=terms),
            patch.object(render, "_test_types_for", return_value={"Max_Val": _test_type("Max_Val")}),
            patch.object(render, "_table_group_for", return_value=TableGroup(id=uuid4(), connection_id=1)),
            patch.object(render, "_flavor_code_for", return_value="postgresql"),
            patch.object(render, "_conditions_for", return_value={}),
            patch.object(render, "_column_types_for", return_value={}),
        ):
            document = render_document(stored)
        prop = next(p for p in document["schema"][0]["properties"] if p["name"] == "c_max")
        assert "logicalTypeOptions" not in prop
        assert resolve_declarations(prop, frozenset(_CATALOGUE)) == []
