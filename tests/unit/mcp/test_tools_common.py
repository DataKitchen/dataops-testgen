from uuid import UUID

import pytest

from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.tools.common import parse_result_status, parse_uuid

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
