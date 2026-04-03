from uuid import UUID

import pandas as pd
import pytest

from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.tools.common import dataframe_to_markdown, parse_result_status, parse_uuid

# --- parse_uuid ---


def test_parse_uuid_valid():
    raw = "12345678-1234-5678-1234-567812345678"
    result = parse_uuid(raw)
    assert result == UUID(raw)


def test_parse_uuid_valid_no_dashes():
    raw = "12345678123456781234567812345678"
    result = parse_uuid(raw)
    assert isinstance(result, UUID)


def test_parse_uuid_invalid():
    with pytest.raises(MCPUserError, match="not a valid UUID"):
        parse_uuid("not-a-uuid")


def test_parse_uuid_empty():
    with pytest.raises(MCPUserError, match="not a valid UUID"):
        parse_uuid("")


def test_parse_uuid_custom_label():
    with pytest.raises(MCPUserError, match="Invalid test_run_id"):
        parse_uuid("bad", label="test_run_id")


# --- parse_result_status ---


def test_parse_result_status_valid():
    assert parse_result_status("Failed") == TestResultStatus.Failed
    assert parse_result_status("Passed") == TestResultStatus.Passed
    assert parse_result_status("Warning") == TestResultStatus.Warning


def test_parse_result_status_invalid():
    with pytest.raises(MCPUserError, match="Invalid status `BadStatus`"):
        parse_result_status("BadStatus")


def test_parse_result_status_invalid_lists_valid_values():
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_result_status("nope")
    for status in TestResultStatus:
        assert status.value in str(exc_info.value)


# --- dataframe_to_markdown ---


def test_dataframe_to_markdown_basic():
    df = pd.DataFrame({"name": ["Alice", "Bob"], "score": [95, 87]})
    result = dataframe_to_markdown(df)

    assert "| name | score |" in result
    assert "| --- | --- |" in result
    assert "| Alice | 95 |" in result
    assert "| Bob | 87 |" in result


def test_dataframe_to_markdown_none():
    assert dataframe_to_markdown(None) == "_No rows._"


def test_dataframe_to_markdown_empty():
    df = pd.DataFrame({"col": []})
    assert dataframe_to_markdown(df) == "_No rows._"


def test_dataframe_to_markdown_null_values():
    df = pd.DataFrame({"a": [1, None], "b": [None, "x"]})
    result = dataframe_to_markdown(df)

    lines = result.split("\n")
    data_rows = lines[2:]
    assert "| 1.0 | _NULL_ |" == data_rows[0]
    assert "| _NULL_ | x |" == data_rows[1]


def test_dataframe_to_markdown_custom_null_display():
    df = pd.DataFrame({"a": [None]})
    result = dataframe_to_markdown(df, null_display="<null>")

    assert "| <null> |" in result


def test_dataframe_to_markdown_escapes_pipes_in_values():
    df = pd.DataFrame({"col": ['{"a"|"b"}', "no pipes"]})
    result = dataframe_to_markdown(df)

    lines = result.split("\n")
    assert r'| {"a"\|"b"} |' == lines[2]
    assert "| no pipes |" == lines[3]


def test_dataframe_to_markdown_escapes_pipes_in_headers():
    df = pd.DataFrame({"col|name": [1]})
    result = dataframe_to_markdown(df)

    assert r"| col\|name |" in result
