"""Tests that MCP handlers run on worker threads inside the shared session limit, off the event loop."""

import asyncio
import threading
import time
from unittest.mock import patch

import anyio
import pytest

from testgen.mcp.permissions import get_mcp_username, set_mcp_username
from testgen.mcp.server import _run_on_worker_thread, build_mcp_server

pytestmark = pytest.mark.unit


def test_handlers_run_side_by_side_and_leave_the_event_loop_free():
    # Each call waits for the other to start, so they finish only if they run at the same time.
    both_running = threading.Barrier(2, timeout=2)

    def tool(n: int) -> int:
        both_running.wait()
        return n

    wrapped = _run_on_worker_thread(tool)
    loop_ticked = False

    async def ticker():
        nonlocal loop_ticked
        await asyncio.sleep(0)
        loop_ticked = True

    async def main():
        return await asyncio.gather(wrapped(1), wrapped(2), ticker())

    results = asyncio.run(main())

    assert results[:2] == [1, 2]
    assert loop_ticked


def test_a_handler_sees_the_callers_identity():
    wrapped = _run_on_worker_thread(get_mcp_username)

    async def main():
        set_mcp_username("alice")
        return await wrapped()

    assert asyncio.run(main()) == "alice"


def test_no_more_handlers_run_at_once_than_the_session_limit():
    running = 0
    peak = 0
    lock = threading.Lock()

    def tool() -> None:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1

    async def main():
        limiter = anyio.CapacityLimiter(2)
        with patch("testgen.mcp.server.session_limiter", return_value=limiter):
            wrapped = _run_on_worker_thread(tool)
            await asyncio.gather(*(wrapped() for _ in range(6)))

    asyncio.run(main())

    assert peak == 2


def test_busy_mcp_handlers_leave_session_slots_for_rest_requests():
    release = threading.Event()

    def blocked_tool() -> None:
        release.wait(timeout=2)

    async def main():
        session = anyio.CapacityLimiter(4)
        mcp = anyio.CapacityLimiter(2)
        with (
            patch("testgen.mcp.server.session_limiter", return_value=session),
            patch("testgen.mcp.server._mcp_limiter", return_value=mcp),
        ):
            wrapped = _run_on_worker_thread(blocked_tool)
            calls = [asyncio.create_task(wrapped()) for _ in range(5)]
            while mcp.borrowed_tokens < 2:
                await asyncio.sleep(0.01)
            with anyio.fail_after(1):
                async with session:
                    rest_got_a_slot = True
            release.set()
            await asyncio.gather(*calls)
        return rest_got_a_slot

    assert asyncio.run(main())


def test_registered_handlers_are_async_and_keep_their_parameters():
    server = build_mcp_server(api_base_url="https://testgen.example.com")
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert all(tool.is_async for tool in tools.values())
    assert "test_suite_id" in tools["generate_tests"].parameters["properties"]

    templates = [template.uri_template for template in server._resource_manager.list_templates()]
    assert "testgen://connection-parameters/{flavor}" in templates

    prompts = {prompt.name: prompt for prompt in server._prompt_manager.list_prompts()}
    assert "test_suite" in [argument.name for argument in prompts["investigate_failures"].arguments]
