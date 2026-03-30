"""Tests for the mcp_error_boundary decorator."""

import logging

from testgen.mcp.exceptions import MCPPermissionDenied, MCPUserError, mcp_error_handler


def test_returns_normal_result():
    @mcp_error_handler
    def my_tool(x: int) -> str:
        return f"result: {x}"

    assert my_tool(42) == "result: 42"


def test_converts_mcp_user_error_to_string():
    @mcp_error_handler
    def failing_tool():
        raise MCPUserError("Invalid table_group_id: `abc` is not a valid UUID.")

    assert failing_tool() == "Invalid table_group_id: `abc` is not a valid UUID."


def test_converts_permission_denied_to_string():
    @mcp_error_handler
    def restricted_tool():
        raise MCPPermissionDenied("Your role does not include the necessary permission.")

    assert restricted_tool() == "Your role does not include the necessary permission."


def test_catches_unexpected_error_and_returns_neutral_message():
    @mcp_error_handler
    def broken_tool():
        raise RuntimeError("DB connection pool exhausted")

    result = broken_tool()
    assert result == "An unexpected error occurred."
    assert "DB connection pool" not in result


def test_logs_unexpected_error_traceback(caplog):
    @mcp_error_handler
    def broken_tool():
        raise RuntimeError("secret internal detail")

    with caplog.at_level(logging.ERROR, logger="testgen"):
        broken_tool()

    assert "secret internal detail" in caplog.text
    assert "broken_tool" in caplog.text


def test_preserves_function_metadata():
    @mcp_error_handler
    def my_tool(x: int, y: str = "default") -> str:
        """Tool docstring."""
        return f"{x}-{y}"

    assert my_tool.__name__ == "my_tool"
    assert my_tool.__doc__ == "Tool docstring."
