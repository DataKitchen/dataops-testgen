"""The schema-name rule, which every surface that takes one has to apply identically.

The pattern is handed to Pydantic for the REST body and used directly here for MCP and for
create. Pydantic anchors a pattern as a full match; anything that anchors it more loosely lets a
value through one surface that the other rejects, and the value reaches the target database by
substitution.

The rule excludes what would end the quoting the templates put the name inside, rather than
restricting it to a bare identifier: a schema a table group can be created on is one it can be
moved to.
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
        "Sales-Data_2026_09",
        "Sales Data",
        "9leading_digit",
        "a" * SCHEMA_NAME_MAX_LENGTH,
    ],
)
def test_accepts_a_name_the_templates_can_quote(value):
    assert validate_schema_name(value) is None
    assert _rest_accepts(value)


@pytest.mark.parametrize(
    "value",
    [
        "public\n",
        "public\nDROP TABLE x",
        'x" OR 1=1--',
        "x' OR 1=1--",
        "with`backtick",
        "with\ttab",
        "",
        "a" * (SCHEMA_NAME_MAX_LENGTH + 1),
    ],
)
def test_rejects_what_would_end_the_quoting(value):
    assert validate_schema_name(value) is not None
    assert not _rest_accepts(value)


def test_the_two_surfaces_agree_on_a_trailing_newline():
    """``re.match`` stops at the newline and reports a match; Pydantic's engine does not. Matching
    loosely here would accept a value the REST body rejects, and it reaches the SQL quoted."""
    assert re.match(SCHEMA_NAME_PATTERN, "public\n"), "precondition: a loose anchor would accept it"

    assert validate_schema_name("public\n") is not None
    assert not _rest_accepts("public\n")
