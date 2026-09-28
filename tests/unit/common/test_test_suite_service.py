"""Tests for ``validate_test_suite_fields``."""

from unittest.mock import patch

import pytest

from testgen.common.database.test_suite_service import validate_test_suite_fields
from testgen.common.enums import SuiteType
from testgen.common.models.test_suite import TestSuite

pytestmark = pytest.mark.unit


def _suite(**overrides) -> TestSuite:
    defaults = {
        "project_code": "demo",
        "test_suite": "Orders",
        "suite_type": SuiteType.REGULAR,
    }
    defaults.update(overrides)
    return TestSuite(**defaults)


@pytest.fixture
def generation_sets():
    with patch(
        "testgen.common.generation_set_service.list_generation_sets", return_value=["Quick", "Standard"]
    ) as mock:
        yield mock


def test_validate_passes_baseline():
    assert validate_test_suite_fields(_suite()) == []


@pytest.mark.parametrize("name", [None, "", "   "])
def test_validate_requires_a_name(name):
    assert validate_test_suite_fields(_suite(test_suite=name)) == ["`test_suite_name` is required."]


@pytest.mark.parametrize(
    ("attr", "max_length", "message_name"),
    [
        ("test_suite", 200, "test_suite_name"),
        ("test_suite_description", 1000, "description"),
        ("component_key", 100, "component_key"),
        ("component_type", 100, "component_type"),
        ("component_name", 100, "component_name"),
    ],
)
def test_validate_rejects_a_value_wider_than_its_column(attr, max_length, message_name):
    assert validate_test_suite_fields(_suite(**{attr: "x" * max_length})) == []
    assert validate_test_suite_fields(_suite(**{attr: "x" * (max_length + 1)})) == [
        f"`{message_name}` must be at most {max_length} characters.",
    ]


@pytest.mark.parametrize("severity", [None, "Fail", "Warning", "Log"])
def test_validate_accepts_the_severities_execution_recognizes(severity):
    assert validate_test_suite_fields(_suite(severity=severity)) == []


@pytest.mark.parametrize("severity", ["Failed", "Inherit", "fail", "Critical"])
def test_validate_rejects_other_severities(severity):
    assert validate_test_suite_fields(_suite(severity=severity)) == [
        "`default_severity` must be one of Fail, Warning, Log.",
    ]


def test_validate_skips_generation_sets_when_unset(generation_sets):
    assert validate_test_suite_fields(_suite(generation_sets=None)) == []
    generation_sets.assert_not_called()


def test_validate_accepts_defined_generation_sets(generation_sets):
    assert validate_test_suite_fields(_suite(generation_sets=["Standard", "Quick"])) == []


@pytest.mark.parametrize(
    ("requested", "fragment"),
    [
        (["Nope"], "Unknown generation sets: Nope."),
        (["Monitor"], "'Monitor' cannot be used for a regular test suite."),
        ([], "At least one generation set is required."),
    ],
)
def test_validate_reports_the_generation_set_rule_broken(generation_sets, requested, fragment):
    errors = validate_test_suite_fields(_suite(generation_sets=requested))

    assert len(errors) == 1
    assert errors[0].startswith("`generation_sets`: ")
    assert fragment in errors[0]


def test_validate_reports_every_failure_together(generation_sets):
    errors = validate_test_suite_fields(_suite(
        test_suite="",
        component_name="x" * 101,
        severity="Failed",
        generation_sets=["Nope"],
    ))

    assert errors[:3] == [
        "`test_suite_name` is required.",
        "`component_name` must be at most 100 characters.",
        "`default_severity` must be one of Fail, Warning, Log.",
    ]
    assert errors[3].startswith("`generation_sets`: Unknown generation sets")


def test_validate_names_fields_by_the_supplied_mapping():
    errors = validate_test_suite_fields(
        _suite(test_suite="", severity="Critical"),
        field_names={"severity": "severity_default"},
    )

    assert errors == [
        "`test_suite_name` is required.",
        "`severity_default` must be one of Fail, Warning, Log.",
    ]


def test_validate_can_leave_field_names_unquoted():
    errors = validate_test_suite_fields(
        _suite(test_suite=""),
        field_names={"test_suite": "Test Suite Name"},
        quote_fields=False,
    )

    assert errors == ["Test Suite Name is required."]
