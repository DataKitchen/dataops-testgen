from decimal import Decimal

import pytest

from testgen.common.clean_sql import (
    CleanSQL,
    NonNumericValueError,
    concat_columns,
    format_value_list,
    normalize_value_list,
    parse_numeric_values,
    parse_value_list,
    strip_trailing_semicolons,
)

pytestmark = pytest.mark.unit


# --- CleanSQL ---

def test_clean_sql_block_comments():
    assert CleanSQL("SELECT /* comment */ 1") == "SELECT 1"


def test_clean_sql_multiline_block_comments():
    sql = """SELECT /*
    multi-line
    comment
    */ 1"""
    assert CleanSQL(sql) == "SELECT 1"


def test_clean_sql_line_comments():
    sql = "SELECT 1 -- this is a comment\nFROM t"
    assert CleanSQL(sql) == "SELECT 1 FROM t"


def test_clean_sql_tabs_and_extra_spaces():
    sql = "SELECT\t  1\t\tFROM   t"
    assert CleanSQL(sql) == "SELECT 1 FROM t"


def test_clean_sql_preserves_quoted_strings():
    sql = "SELECT '  spaces  ' FROM t"
    result = CleanSQL(sql)
    assert "'  spaces  '" in result


def test_clean_sql_preserves_double_quoted_strings():
    sql = 'SELECT "  col  name  " FROM t'
    result = CleanSQL(sql)
    assert '"  col  name  "' in result


def test_clean_sql_combined():
    sql = """
    SELECT /* get all */
        col1,   col2
    FROM   table1 -- main table
    WHERE  col1 = 'hello  world'
    """
    result = CleanSQL(sql)
    assert "/* get all */" not in result
    assert "-- main table" not in result
    assert "'hello  world'" in result
    assert "col1, col2" in result


# --- concat_columns ---

def test_concat_columns_multiple():
    result = concat_columns("col1, col2, col3", "NULL")
    assert result == "CONCAT(COALESCE(col1, 'NULL'), COALESCE(col2, 'NULL'), COALESCE(col3, 'NULL'))"


def test_concat_columns_single():
    assert concat_columns("col1", "NULL") == "col1"


def test_concat_columns_empty():
    assert concat_columns("", "NULL") == ""


def test_concat_columns_none():
    assert concat_columns(None, "NULL") == ""


# --- parse_value_list ---

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ("", []),
        ('""', [""]),
        ('"",n/a,none', ["", "n/a", "none"]),
        ("a, b,c", ["a", "b", "c"]),
        ('"a,b",c', ["a,b", "c"]),
        ('"it""s"', ['it"s']),
        ("it's", ["it's"]),
        ("a\\b", ["a\\b"]),
        ('" "," x"', [" ", " x"]),
    ],
)
def test_parse_value_list(value, expected):
    assert parse_value_list(value) == expected


# --- parse_numeric_values ---

def test_parse_numeric_values_keeps_the_first_of_values_equal_as_numbers():
    numbers = parse_numeric_values(["1.5", "2", "1.50", " 2.0 ", "-0.5", "1e2", "100"])
    assert [str(number) for number in numbers] == ["1.5", "2", "-0.5", "1E+2"]


def test_parse_numeric_values_accepts_an_empty_list():
    assert parse_numeric_values([]) == []


@pytest.mark.parametrize("value", ["a", "", "1,5", "NaN", "Infinity", "-inf", "0x10", "1_000", "\u0663", "1e", "."])
def test_parse_numeric_values_rejects_a_value_that_is_not_a_finite_number(value):
    with pytest.raises(NonNumericValueError) as error:
        parse_numeric_values(["1", value])
    assert error.value.value == value
    assert str(error.value) == f"List of Expected Values contains a value that is not a number: {value}."


def test_parse_numeric_values_returns_decimals():
    assert parse_numeric_values(["0.1"]) == [Decimal("0.1")]


# --- format_value_list / normalize_value_list ---

@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["Y", "N"], "Y,N"),
        (["", "a,b", 'say "hi"', "it's"], '"","a,b","say ""hi""",it\'s'),
        ([" lead", "trail ", "\ttab"], '" lead","trail ","\ttab"'),
        (["line\nbreak", "cr\rhere"], '"line\nbreak","cr\rhere"'),
        (["a|b", "ü"], "a|b,ü"),
        ([], ""),
    ],
)
def test_format_value_list_reads_back_with_parse_value_list(values, expected):
    assert format_value_list(values) == expected
    assert parse_value_list(expected) == values


@pytest.mark.parametrize(
    ("value", "numeric", "expected"),
    [
        ("1.5, 2,1.50, 2.0", True, "1.5,2"),
        (" 10 ,1e1", True, "10"),
        ("a,A,a", False, "a,A"),
        ('a, "a",x', False, "a,x"),
        ('"",a,""', False, '"",a'),
        ("e,é", False, "e,é"),
    ],
)
def test_normalize_value_list_keeps_each_value_once(value, numeric, expected):
    assert normalize_value_list(value, numeric) == expected


def test_normalize_value_list_rejects_a_non_number_in_a_numeric_list():
    with pytest.raises(NonNumericValueError) as error:
        normalize_value_list("1,two", numeric=True)
    assert error.value.value == "two"


# --- strip_trailing_semicolons ---

@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (None, None),
        ("", ""),
        ("SELECT 1", "SELECT 1"),
        ("SELECT 1;", "SELECT 1"),
        ("SELECT 1 ; \n ;\n", "SELECT 1"),
        ("SELECT ';' AS s", "SELECT ';' AS s"),
    ],
)
def test_strip_trailing_semicolons(sql, expected):
    assert strip_trailing_semicolons(sql) == expected
