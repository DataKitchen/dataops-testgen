"""Variables a custom query declares, and the values a run gives them."""

import pytest

from testgen.common.query_variables import (
    declared_variables,
    render,
    validate_declarations,
    validate_values,
    values_for_run,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# What counts as a declaration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("SELECT 1", {}),
        (None, {}),
        ("WHERE d > '{END_DATE:2026-10-10}'", {"END_DATE": "2026-10-10"}),
        ("{A:1} AND {B:2}", {"A": "1", "B": "2"}),
        # The default runs to the brace, so it may hold a colon.
        ("{AT:2026-10-10 12:30:00}", {"AT": "2026-10-10 12:30:00"}),
        ("{EMPTY:}", {"EMPTY": ""}),
        # A parameter TestGen fills in is not a variable, declared with a default or without.
        ("SELECT * FROM {DATA_SCHEMA}.t", {}),
        # Without a default it is not yet a usable declaration; validate_declarations rejects it.
        ("{END_DATE}", {}),
    ],
)
def test_declared_variables(query, expected):
    assert declared_variables(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "WHERE x ~ 'a{2,4}'",
        "WHERE d > {d '2026-01-01'}",
        """SELECT '{"key": "value"}'::jsonb""",
        "WHERE x ~ '{2,4}' AND y = '{lower}'",
        # A leading digit or lower-case letter is not a name, so neither is a declaration.
        "{1ST:x} {lower:x}",
    ],
)
def test_other_brace_syntax_is_left_alone(query):
    """SQL is full of braces. Only a capitalised name makes a declaration."""
    assert declared_variables(query) == {}
    assert validate_declarations(query) is None
    assert render(query) == query


# ---------------------------------------------------------------------------
# Save-time validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query",
    ["SELECT 1", None, "", "{END_DATE:2026-10-10}", "SELECT * FROM {DATA_SCHEMA}.t", "{A:1} {B:2}"],
)
def test_validate_declarations_accepts(query):
    assert validate_declarations(query) is None


def test_a_variable_without_a_default_is_rejected():
    assert validate_declarations("WHERE d > '{END_DATE}'") == (
        "Variable END_DATE needs a default value, written as {END_DATE:value}"
    )


def test_a_parameter_testgen_fills_in_cannot_be_declared():
    assert validate_declarations("SELECT * FROM {DATA_SCHEMA:public}.t") == (
        "DATA_SCHEMA is filled in by TestGen and cannot be used as a variable"
    )


def test_the_first_problem_is_the_one_reported():
    assert validate_declarations("{A:1} {MISSING} {RUN_DATE:x}") == (
        "Variable MISSING needs a default value, written as {MISSING:value}"
    )


# ---------------------------------------------------------------------------
# Run-supplied values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("values", [None, {}, {"END_DATE": "2026-10-17"}, {"A1_B": "x"}])
def test_validate_values_accepts(values):
    assert validate_values(values) is None


def test_a_lower_case_key_is_rejected():
    assert validate_values({"end_date": "x"}) == (
        "`end_date` is not a valid variable name. Use capital letters, digits, and underscores, "
        "starting with a letter."
    )


@pytest.mark.parametrize("name", ["1ST", "WITH SPACE", "WITH-DASH", ""])
def test_a_key_that_is_not_a_name_is_rejected(name):
    assert "is not a valid variable name" in validate_values({name: "x"})


def test_a_key_testgen_fills_in_is_rejected():
    assert validate_values({"DATA_SCHEMA": "public"}) == (
        "`DATA_SCHEMA` is filled in by TestGen and cannot be used as a variable."
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def test_a_variable_takes_its_default_when_the_run_gives_no_value():
    assert render("WHERE d > '{END_DATE:2026-10-10}'") == "WHERE d > '2026-10-10'"


def test_a_run_value_replaces_the_default():
    assert render("WHERE d > '{END_DATE:2026-10-10}'", {"END_DATE": "2026-10-17"}) == (
        "WHERE d > '2026-10-17'"
    )


def test_a_key_no_declaration_matches_is_ignored():
    assert render("WHERE d > '{END_DATE:2026-10-10}'", {"OTHER": "x"}) == "WHERE d > '2026-10-10'"


def test_a_parameter_is_left_for_the_parameter_dictionary():
    """``{DATA_SCHEMA}`` is substituted later, so rendering must not consume it."""
    assert render("SELECT * FROM {DATA_SCHEMA}.t", {"DATA_SCHEMA": "ignored"}) == (
        "SELECT * FROM {DATA_SCHEMA}.t"
    )


def test_a_value_is_inserted_as_text_and_not_scanned_again():
    """A value holding brace syntax is inert: nothing re-reads the rendered query for
    declarations, so it cannot introduce one."""
    assert render("{A:x}", {"A": "{B:y}"}) == "{B:y}"


def test_a_value_naming_a_parameter_does_not_expand_here():
    """The declaration is resolved before the query enters the parameter dictionary, so a value
    mentioning a parameter is left for that pass rather than expanded by this one."""
    assert render("{A:x}", {"A": "{DATA_SCHEMA}"}) == "{DATA_SCHEMA}"


@pytest.mark.parametrize("query", [None, ""])
def test_rendering_a_query_that_is_not_there(query):
    assert render(query) == query


def test_values_for_run_records_defaults_and_overrides_together():
    """A result records what it ran with, so a variable left at its default is recorded too."""
    assert values_for_run("{A:1} {B:2}", {"B": "9", "UNUSED": "x"}) == {"A": "1", "B": "9"}


def test_values_for_run_is_empty_when_a_query_declares_nothing():
    assert values_for_run("SELECT * FROM {DATA_SCHEMA}.t", {"A": "1"}) == {}
