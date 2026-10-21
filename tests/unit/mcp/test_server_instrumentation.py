# The stub handlers are coroutine functions so the coroutine wrappers are exercised; they need not
# await anything. RUF029 is a false positive for that pattern.
# ruff: noqa: RUF029

import asyncio
import inspect
import threading
from unittest.mock import patch

import anyio
import pytest

from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import set_mcp_username
from testgen.mcp.server import HandlerKind, MCPCallStatus, _instrument


def _emit_capture():
    calls = []

    def fake_send_event(self, event_name, include_usage=False, **properties):
        calls.append((event_name, properties))

    return calls, fake_send_event


def test_instrument_emits_success_event():
    set_mcp_username("alice")
    calls, fake = _emit_capture()

    def my_tool():
        return "ok"

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        wrapped = _instrument(my_tool, HandlerKind.TOOL)
        assert wrapped() == "ok"

    assert len(calls) == 1
    event_name, props = calls[0]
    assert event_name == "mcp-call"
    assert props["kind"] == HandlerKind.TOOL
    assert props["handler_name"] == "my_tool"
    assert props["username"] == "alice"
    assert props["status"] == MCPCallStatus.SUCCESS
    assert isinstance(props["latency_ms"], int)


def test_instrument_resource_emits_event():
    set_mcp_username("alice")
    calls, fake = _emit_capture()

    def my_resource():
        return "doc"

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        wrapped = _instrument(my_resource, HandlerKind.RESOURCE)
        assert wrapped() == "doc"

    event_name, props = calls[0]
    assert event_name == "mcp-call"
    assert props["kind"] == HandlerKind.RESOURCE
    assert props["handler_name"] == "my_resource"
    assert props["status"] == MCPCallStatus.SUCCESS


def test_instrument_prompt_emits_event():
    set_mcp_username("alice")
    calls, fake = _emit_capture()

    def my_prompt():
        return "template"

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        wrapped = _instrument(my_prompt, HandlerKind.PROMPT)
        assert wrapped() == "template"

    event_name, props = calls[0]
    assert event_name == "mcp-call"
    assert props["kind"] == HandlerKind.PROMPT
    assert props["handler_name"] == "my_prompt"
    assert props["status"] == MCPCallStatus.SUCCESS


def test_instrument_permission_denied_status():
    set_mcp_username("alice")
    calls, fake = _emit_capture()

    def denied_tool():
        raise MCPResourceNotAccessible("Project", "demo")

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        wrapped = _instrument(denied_tool, HandlerKind.TOOL)
        with pytest.raises(MCPPermissionDenied):
            wrapped()

    assert calls[0][1]["status"] == MCPCallStatus.PERMISSION_DENIED


def test_instrument_user_error_status():
    set_mcp_username("alice")
    calls, fake = _emit_capture()

    def bad_input():
        raise MCPUserError("invalid uuid")

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        wrapped = _instrument(bad_input, HandlerKind.TOOL)
        with pytest.raises(MCPUserError):
            wrapped()

    assert calls[0][1]["status"] == MCPCallStatus.USER_ERROR


def test_instrument_error_status():
    set_mcp_username("alice")
    calls, fake = _emit_capture()

    def boom():
        raise ValueError("nope")

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        wrapped = _instrument(boom, HandlerKind.TOOL)
        with pytest.raises(ValueError):
            wrapped()

    assert calls[0][1]["status"] == MCPCallStatus.ERROR


def test_instrument_preserves_name():
    def my_tool():
        return "ok"

    assert _instrument(my_tool, HandlerKind.TOOL).__name__ == "my_tool"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (None, MCPCallStatus.SUCCESS),
        (MCPUserError("Nothing was deleted."), MCPCallStatus.USER_ERROR),
        (MCPPermissionDenied("denied"), MCPCallStatus.PERMISSION_DENIED),
        (RuntimeError("boom"), MCPCallStatus.ERROR),
    ],
)
def test_instrument_records_a_coroutine_functions_outcome(error, status):
    calls, fake = _emit_capture()

    async def my_tool():
        if error:
            raise error
        return "ok"

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        wrapped = _instrument(my_tool, HandlerKind.TOOL)
        assert inspect.iscoroutinefunction(wrapped)
        if error:
            with pytest.raises(type(error)):
                asyncio.run(wrapped())
        else:
            assert asyncio.run(wrapped()) == "ok"

    assert [props["status"] for _, props in calls] == [status]
    assert calls[0][1]["handler_name"] == "my_tool"


def test_instrument_sends_a_coroutine_functions_event_off_the_event_loop():
    """Building the event can read the database, which must not happen on the loop the server shares."""
    threads = []

    def fake_send_event(self, event_name, include_usage=False, **properties):
        threads.append(threading.get_ident())

    async def my_tool():
        return threading.get_ident()

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake_send_event):
        loop_thread = asyncio.run(_instrument(my_tool, HandlerKind.TOOL)())

    assert len(threads) == 1
    assert threads[0] != loop_thread


def test_instrument_records_a_cancelled_coroutine_function_as_cancelled():
    calls, fake = _emit_capture()
    started = asyncio.Event()

    async def my_tool():
        started.set()
        await asyncio.sleep(10)

    async def main():
        task = asyncio.create_task(_instrument(my_tool, HandlerKind.TOOL)())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        asyncio.run(main())

    assert [props["status"] for _, props in calls] == [MCPCallStatus.CANCELLED]


def test_instrument_sends_a_coroutine_functions_event_while_every_session_slot_is_taken():
    """The tool's work is done by then; its response must not wait for a database slot it does not need."""
    calls, fake = _emit_capture()

    async def my_tool():
        return "ok"

    async def main():
        full = anyio.CapacityLimiter(1)
        async with full:
            with (
                patch("testgen.mcp.workers.session_limiter", return_value=full),
                patch("testgen.mcp.workers.mcp_limiter", return_value=full),
                anyio.fail_after(2),
            ):
                return await _instrument(my_tool, HandlerKind.TOOL)()

    with patch("testgen.common.mixpanel_service.MixpanelService.send_event", fake):
        assert asyncio.run(main()) == "ok"

    assert [props["status"] for _, props in calls] == [MCPCallStatus.SUCCESS]
