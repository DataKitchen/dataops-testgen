from uuid import UUID

import pytest

from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.tools.common import parse_result_status, parse_uuid, validate_limit, validate_page

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


# --- validate_page ---


@pytest.mark.parametrize("ok", [1, 2, 99])
def test_validate_page_accepts_positive(ok):
    validate_page(ok)  # does not raise


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_validate_page_rejects_below_one(bad):
    with pytest.raises(MCPUserError, match=f"Invalid page `{bad}`"):
        validate_page(bad)


# --- validate_limit ---


@pytest.mark.parametrize("ok", [1, 50, 100])
def test_validate_limit_accepts_in_range(ok):
    validate_limit(ok, 100)  # does not raise


@pytest.mark.parametrize("bad", [0, -1, 101, 1000])
def test_validate_limit_rejects_out_of_range(bad):
    with pytest.raises(MCPUserError, match=f"Invalid limit `{bad}`"):
        validate_limit(bad, 100)


def test_validate_limit_message_includes_max():
    with pytest.raises(MCPUserError, match="between 1 and 200"):
        validate_limit(0, 200)
