"""The schema-name rule, which both caller-supplied surfaces have to apply identically.

The pattern is handed to Pydantic for the REST body and used directly here for MCP. Pydantic
anchors a pattern as a full match; anything that anchors it more loosely lets a value through one
surface that the other rejects, and the value reaches the target database by substitution.
"""

import re

import pytest
from pydantic import BaseModel, Field, ValidationError

from testgen.common.models.table_group import (
    SCHEMA_NAME_MAX_LENGTH,
    SCHEMA_NAME_PATTERN,
    validate_schema_name,
)

pytestmark = pytest.mark.unit


class _RestBody(BaseModel):
    """Stands in for the request field, bound the same way."""

    schema_name: str = Field(pattern=SCHEMA_NAME_PATTERN, max_length=SCHEMA_NAME_MAX_LENGTH)


def _rest_accepts(value: str) -> bool:
    try:
        _RestBody(schema_name=value)
    except ValidationError:
        return False
    return True


@pytest.mark.parametrize(
    "value",
    [
        "public",
        "onboard_2026_09_10",
        "_leading_underscore",
        "with$dollar",
        "a" * SCHEMA_NAME_MAX_LENGTH,
    ],
)
def test_accepts_a_bare_identifier(value):
    assert validate_schema_name(value) is None
    assert _rest_accepts(value)


@pytest.mark.parametrize(
    "value",
    [
        "public\n",
        "public\nDROP TABLE x",
        'x" OR 1=1--',
        "has space",
        "has-hyphen",
        "9leading_digit",
        "",
        "a" * (SCHEMA_NAME_MAX_LENGTH + 1),
    ],
)
def test_rejects_anything_that_is_not_one(value):
    assert validate_schema_name(value) is not None
    assert not _rest_accepts(value)


def test_the_two_surfaces_agree_on_a_trailing_newline():
    """``re.match`` stops at the newline and reports a match; Pydantic's engine does not. Matching
    loosely here would accept a value the REST body rejects, and it reaches the SQL quoted."""
    assert re.match(SCHEMA_NAME_PATTERN, "public\n"), "precondition: a loose anchor would accept it"

    assert validate_schema_name("public\n") is not None
    assert not _rest_accepts("public\n")
