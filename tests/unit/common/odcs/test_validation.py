import json
from importlib import resources

import pytest

from testgen.common.contract_service import _LOGICAL_TYPE_FROM_GENERAL_TYPE, _logical_type
from testgen.common.enums import OdcsDimension
from testgen.common.models.data_column import DataColumnChars
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND, ServerType
from testgen.common.odcs.validation import validate_document

pytestmark = pytest.mark.unit


def _minimal_document() -> dict:
    return {
        "apiVersion": ODCS_API_VERSION,
        "kind": ODCS_KIND,
        "id": "test-contract",
        "version": "1.0.0",
    }


def _schema() -> dict:
    return json.loads(
        resources.files("testgen.common.odcs.schemas").joinpath("odcs-json-schema-v3.2.0.json").read_text()
    )


def test_a_minimal_valid_document_produces_no_messages():
    assert validate_document(_minimal_document()) == []


@pytest.mark.parametrize(
    ("field", "value", "fmt"),
    [
        ("servers", [{"server": "lake", "type": "s3", "location": "no scheme here"}], "uri"),
        ("contractCreatedTs", "yesterday", "date-time"),
    ],
)
def test_the_formats_that_need_a_checker_package_are_checked(field, value, fmt):
    document = _minimal_document() | {field: value}
    messages = validate_document(document)
    assert any(f"is not a '{fmt}'" in message for message in messages), messages


def test_an_invalid_document_reports_the_validators_own_message():
    document = _minimal_document() | {"kind": "NotAContract"}
    messages = validate_document(document)
    assert any("NotAContract" in message for message in messages)


def test_every_violation_is_reported_not_only_the_first():
    document = {"apiVersion": "v3.2.0"}  # missing kind, id and version
    assert len(validate_document(document)) >= 3


def test_a_document_with_no_api_version_falls_back_to_the_pinned_schema():
    """The schema requires ``apiVersion``, so such a document is invalid either way. What the
    fallback decides is which schema says so -- the missing field, not an unknown version."""
    document = {key: value for key, value in _minimal_document().items() if key != "apiVersion"}

    assert validate_document(document) == ["$: 'apiVersion' is a required property"]


@pytest.mark.parametrize("declared", ["v3.1.0", "v2.2.0"])
def test_an_api_version_the_standard_allows_but_we_do_not_bundle_is_a_reported_problem(declared):
    """These are legal ODCS -- the schema's own ``apiVersion`` enum accepts eight versions and
    we bundle one. A document declaring another is a document we cannot check, which belongs in
    the problem list beside every other violation rather than coming out as an exception."""
    problems = validate_document(_minimal_document() | {"apiVersion": declared})

    assert problems, f"{declared} was accepted without a bundled schema to check it against"
    assert any(declared in problem and "apiVersion" in problem for problem in problems)


def test_a_document_is_checked_against_the_version_it_declares():
    """Not against a version supplied alongside it: a document validated against someone
    else's ruler reports clean while saying it is something we never checked."""
    document = _minimal_document() | {"apiVersion": "v3.1.0"}

    assert validate_document(document) != [], "the declared version was ignored"


def test_an_api_version_outside_the_standard_is_also_a_reported_problem():
    problems = validate_document(_minimal_document() | {"apiVersion": "v9.9.9"})
    assert any("v9.9.9" in problem for problem in problems)


def test_a_root_quality_key_is_rejected():
    document = _minimal_document() | {"quality": []}
    assert validate_document(document)


def test_the_server_type_enum_matches_the_schema():
    # The ticket text says 34 values. The schema holds 44 and ServerType transcribes all
    # 44 -- this test exists so nobody trims it to match the prose. Set difference must be
    # empty in both directions.
    schema_values = set(_schema()["$defs"]["Server"]["properties"]["type"]["enum"])
    code_values = {member.value for member in ServerType}
    assert code_values == schema_values


def test_the_dimension_enum_matches_the_schema():
    # Set difference must be empty in both directions -- otherwise the enum is a second,
    # hand-maintained copy of the schema's vocabulary with nothing keeping the two honest.
    schema_values = set(_schema()["$defs"]["DataQuality"]["properties"]["dimension"]["enum"])
    code_values = {member.value for member in OdcsDimension}
    assert code_values == schema_values


def test_every_emitted_logical_type_is_in_the_schema_enum():
    # SchemaBaseProperty.logicalType has 11 values. Calls the actual function rather than
    # reading the dict's values, so the "D" branch -- general_type == "D" resolves to
    # "date" or "timestamp" by column_type, bypassing the dict entirely -- is covered too.
    # Driven from the dict's own keys plus "D", the input domain _logical_type branches on,
    # so a general_type added later is caught rather than silently uncovered.
    schema_values = set(_schema()["$defs"]["SchemaBaseProperty"]["properties"]["logicalType"]["enum"])

    dict_driven_values = {
        _logical_type(DataColumnChars(general_type=code, column_type=None))
        for code in _LOGICAL_TYPE_FROM_GENERAL_TYPE
    }
    date_value = _logical_type(DataColumnChars(general_type="D", column_type="date"))
    timestamp_value = _logical_type(DataColumnChars(general_type="D", column_type="datetimeoffset"))

    assert date_value == "date"
    assert timestamp_value == "timestamp"
    assert dict_driven_values | {date_value, timestamp_value} <= schema_values
