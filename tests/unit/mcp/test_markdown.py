from datetime import datetime

import pandas as pd

from testgen.mcp.tools.markdown import (
    MdDoc,
    _escape_inline,
    _escape_table_cell,
    _format_dt,
)

# --- _escape_inline ---


def test_escape_inline_backslash():
    assert _escape_inline(r"a\b") == r"a\\b"


def test_escape_inline_asterisk():
    assert _escape_inline("a*b") == r"a\*b"


def test_escape_inline_underscore():
    assert _escape_inline("a_b") == r"a\_b"


def test_escape_inline_brackets():
    assert _escape_inline("[link](url)") == r"\[link\](url)"


def test_escape_inline_backtick():
    assert _escape_inline("use `code`") == r"use \`code\`"


def test_escape_inline_plain_text():
    assert _escape_inline("hello world 123") == "hello world 123"


def test_escape_inline_multiple_special_chars():
    assert _escape_inline("**bold** and _italic_") == r"\*\*bold\*\* and \_italic\_"


# --- _escape_table_cell ---


def test_escape_table_cell_pipe():
    assert _escape_table_cell("a|b") == r"a\|b"


def test_escape_table_cell_backslash():
    assert _escape_table_cell(r"a\b") == r"a\\b"


def test_escape_table_cell_plain():
    assert _escape_table_cell("hello 123") == "hello 123"


def test_escape_table_cell_asterisk_not_escaped():
    assert _escape_table_cell("a*b") == "a*b"


# --- _format_dt ---


def test_format_dt_datetime_object():
    dt = datetime(2025, 3, 15, 10, 30, 45)
    assert _format_dt(dt) == "2025-03-15 10:30 UTC"


def test_format_dt_iso_string_with_t():
    assert _format_dt("2025-03-15T10:30:45") == "2025-03-15 10:30 UTC"


def test_format_dt_iso_string_with_space():
    assert _format_dt("2025-03-15 10:30:45") == "2025-03-15 10:30 UTC"


def test_format_dt_non_datetime_string():
    assert _format_dt("just a string") is None


def test_format_dt_none():
    assert _format_dt(None) is None


def test_format_dt_integer():
    assert _format_dt(42) is None


# --- MdDoc.heading ---


def test_heading_level_1():
    doc = MdDoc()
    doc.heading(1, "Title")
    assert doc.render() == "# Title"


def test_heading_level_2():
    doc = MdDoc()
    doc.heading(2, "Section")
    assert doc.render() == "## Section"


def test_heading_level_3():
    doc = MdDoc()
    doc.heading(3, "Subsection")
    assert doc.render() == "### Subsection"


# --- MdDoc.field ---


def test_field_string():
    doc = MdDoc()
    doc.field("Name", "Alice")
    assert doc.render() == "- **Name:** Alice"


def test_field_none():
    doc = MdDoc()
    doc.field("Value", None)
    assert doc.render() == "- **Value:** \u2014"


def test_field_datetime():
    doc = MdDoc()
    doc.field("Started", datetime(2025, 3, 15, 10, 30))
    assert doc.render() == "- **Started:** 2025-03-15 10:30 UTC"


def test_field_iso_string():
    doc = MdDoc()
    doc.field("Date", "2025-03-15T10:30:00")
    assert doc.render() == "- **Date:** 2025-03-15 10:30 UTC"


def test_field_code():
    doc = MdDoc()
    doc.field("ID", "abc-123", code=True)
    assert doc.render() == "- **ID:** `abc-123`"


def test_field_code_datetime():
    doc = MdDoc()
    doc.field("Time", datetime(2025, 1, 1, 12, 0), code=True)
    assert doc.render() == "- **Time:** `2025-01-01 12:00 UTC`"


def test_field_no_escaping():
    doc = MdDoc()
    doc.field("Column", "amount_*total*")
    assert doc.render() == "- **Column:** amount_*total*"


def test_field_code_preserves_special_chars():
    doc = MdDoc()
    doc.field("Column", "amount_*total*", code=True)
    assert doc.render() == "- **Column:** `amount_*total*`"


def test_field_code_backtick_in_value_uses_double_fence():
    doc = MdDoc()
    doc.field("Column", "col`name", code=True)
    assert doc.render() == "- **Column:** `` col`name ``"


def test_consecutive_fields_merge():
    doc = MdDoc()
    doc.field("A", "1")
    doc.field("B", "2")
    result = doc.render()
    assert result == "- **A:** 1\n- **B:** 2"
    assert "\n\n" not in result


def test_field_after_heading_starts_new_section():
    doc = MdDoc()
    doc.heading(1, "Title")
    doc.field("A", "1")
    assert doc.render() == "# Title\n\n- **A:** 1"


# --- MdDoc.text ---


def test_text_single_string():
    doc = MdDoc()
    doc.text("Hello world.")
    assert doc.render() == "Hello world."


def test_text_multiple_parts():
    doc = MdDoc()
    doc.text("Showing", 5, "results.")
    assert doc.render() == "Showing 5 results."


def test_text_datetime_part():
    doc = MdDoc()
    doc.text("Since", datetime(2025, 3, 15, 10, 30))
    assert doc.render() == "Since 2025-03-15 10:30 UTC"


def test_text_iso_string_part():
    doc = MdDoc()
    doc.text("Since", "2025-03-15T10:30:00")
    assert doc.render() == "Since 2025-03-15 10:30 UTC"


def test_text_none_part():
    doc = MdDoc()
    doc.text("Value:", None)
    assert doc.render() == "Value: \u2014"


def test_text_empty_skipped():
    doc = MdDoc()
    doc.text()
    assert doc.render() == ""


# --- MdDoc.table ---


def test_table_basic():
    doc = MdDoc()
    doc.table(["Name", "Score"], [["Alice", 95], ["Bob", 87]])
    result = doc.render()
    assert "| Name | Score |" in result
    assert "| --- | --- |" in result
    assert "| Alice | 95 |" in result
    assert "| Bob | 87 |" in result


def test_table_empty_rows():
    doc = MdDoc()
    doc.table(["A", "B"], [])
    assert doc.render() == "_No rows._"


def test_table_null_display():
    doc = MdDoc()
    doc.table(["A"], [[None]], null_display="N/A")
    assert "| N/A |" in doc.render()


def test_table_newline_in_cell_replaced():
    doc = MdDoc()
    doc.table(["Col"], [["line1\nline2"]])
    result = doc.render()
    assert "line1 line2" in result
    assert "\n" not in result.split("\n")[2]  # data row has no raw newline


def test_table_code_columns():
    doc = MdDoc()
    doc.table(["Name", "Table"], [["test1", "my_table"]], code=[1])
    result = doc.render()
    assert "| test1 | `my_table` |" in result


def test_table_code_columns_null_skipped():
    doc = MdDoc()
    doc.table(["Name", "Table"], [["test1", None]], code=[1])
    result = doc.render()
    assert "| test1 | \u2014 |" in result


def test_table_escapes_pipes():
    doc = MdDoc()
    doc.table(["Col"], [["a|b"]])
    assert r"| a\|b |" in doc.render()


def test_table_escapes_pipes_in_headers():
    doc = MdDoc()
    doc.table(["Col|Name"], [["x"]])
    assert r"| Col\|Name |" in doc.render()


def test_table_datetime_in_cell():
    doc = MdDoc()
    doc.table(["Date"], [[datetime(2025, 3, 15, 10, 30)]])
    assert "| 2025-03-15 10:30 UTC |" in doc.render()


def test_table_none_default_display():
    doc = MdDoc()
    doc.table(["A"], [[None]])
    assert "| \u2014 |" in doc.render()


# --- MdDoc.table_from_dataframe ---


def test_table_from_dataframe_basic():
    df = pd.DataFrame({"name": ["Alice", "Bob"], "score": [95, 87]})
    doc = MdDoc()
    doc.table_from_dataframe(df)
    result = doc.render()
    assert "| name | score |" in result
    assert "| Alice | 95 |" in result
    assert "| Bob | 87 |" in result


def test_table_from_dataframe_none():
    doc = MdDoc()
    doc.table_from_dataframe(None)
    assert doc.render() == "_No rows._"


def test_table_from_dataframe_empty():
    doc = MdDoc()
    doc.table_from_dataframe(pd.DataFrame({"col": []}))
    assert doc.render() == "_No rows._"


def test_table_from_dataframe_nan_values():
    df = pd.DataFrame({"a": [1, None], "b": [None, "x"]})
    doc = MdDoc()
    doc.table_from_dataframe(df)
    result = doc.render()
    lines = result.split("\n")
    data_rows = lines[2:]
    assert "| 1.0 | _NULL_ |" == data_rows[0]
    assert "| _NULL_ | x |" == data_rows[1]


def test_table_from_dataframe_escapes_pipes():
    df = pd.DataFrame({"col": ["a|b", "no pipes"]})
    doc = MdDoc()
    doc.table_from_dataframe(df)
    result = doc.render()
    assert r"a\|b" in result


def test_table_from_dataframe_custom_null_display():
    df = pd.DataFrame({"a": [None]})
    doc = MdDoc()
    doc.table_from_dataframe(df, null_display="<null>")
    assert "| <null> |" in doc.render()


# --- MdDoc.bullets ---


def test_bullets_basic():
    doc = MdDoc()
    doc.bullets(["one", "two", "three"])
    assert doc.render() == "- one\n- two\n- three"


def test_bullets_no_escaping():
    doc = MdDoc()
    doc.bullets(["amount_*total*"])
    assert doc.render() == "- amount_*total*"


def test_bullets_preserves_backticks():
    doc = MdDoc()
    doc.bullets(["`orders`", "`customers`"])
    assert "- `orders`" in doc.render()
    assert "- `customers`" in doc.render()


# --- MdDoc.code_block ---


def test_code_block_basic():
    doc = MdDoc()
    doc.code_block("SELECT 1;", language="sql")
    assert doc.render() == "```sql\nSELECT 1;\n```"


def test_code_block_no_language():
    doc = MdDoc()
    doc.code_block("hello")
    assert doc.render() == "```\nhello\n```"


def test_code_block_fence_upgrade():
    doc = MdDoc()
    doc.code_block("contains ``` triple backticks")
    result = doc.render()
    assert result.startswith("````\n")
    assert result.endswith("\n````")
    assert "contains ``` triple backticks" in result


# --- MdDoc.render (multi-section) ---


def test_render_multiple_sections():
    doc = MdDoc()
    doc.heading(1, "Title")
    doc.field("Key", "val")
    doc.text("A paragraph.")
    doc.table(["A"], [["x"]])
    result = doc.render()
    sections = result.split("\n\n")
    assert sections[0] == "# Title"
    assert sections[1] == "- **Key:** val"
    assert sections[2] == "A paragraph."
    assert "| A |" in sections[3]


def test_render_empty_doc():
    assert MdDoc().render() == ""


# --- MdDoc.code ---


def test_code_basic():
    assert MdDoc.code("my_table") == "`my_table`"


def test_code_with_backtick():
    assert MdDoc.code("col`name") == "`` col`name ``"


def test_code_with_newline():
    assert MdDoc.code("line1\nline2") == r"`line1\nline2`"


def test_code_empty():
    assert MdDoc.code("") == "\u2014"


def test_code_none():
    assert MdDoc.code(None) == "\u2014"


# --- MdDoc.escape ---


def test_escape_for_untrusted_data():
    doc = MdDoc()
    doc.field("Note", MdDoc.escape("user typed *bold* and _italic_"))
    assert r"\*bold\*" in doc.render()
    assert r"\_italic\_" in doc.render()


def test_fluent_chaining():
    result = (
        MdDoc()
        .heading(1, "Title")
        .text("Hello.")
        .render()
    )
    assert result == "# Title\n\nHello."
