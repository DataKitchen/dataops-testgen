import pytest

from testgen.common.clean_sql import CleanSQL, concat_columns, parse_value_list, strip_trailing_semicolons

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
