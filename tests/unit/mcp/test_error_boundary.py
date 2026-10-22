"""Tests for the mcp_error_boundary decorator."""

# The stub handlers are coroutine functions so the coroutine wrappers are exercised; they need not
# await anything. RUF029 is a false positive for that pattern.
# ruff: noqa: RUF029

import asyncio
import inspect
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


def test_wraps_a_coroutine_function_as_one():
    @mcp_error_handler
    async def my_tool() -> str:
        return "ok"

    assert inspect.iscoroutinefunction(my_tool)
    assert asyncio.run(my_tool()) == "ok"


def test_converts_a_coroutine_functions_user_error_to_string():
    @mcp_error_handler
    async def failing_tool():
        raise MCPUserError("Nothing was deleted.")

    assert asyncio.run(failing_tool()) == "Nothing was deleted."


def test_catches_a_coroutine_functions_unexpected_error():
    @mcp_error_handler
    async def broken_tool():
        raise RuntimeError("secret internal detail")

    assert asyncio.run(broken_tool()) == "An unexpected error occurred."
