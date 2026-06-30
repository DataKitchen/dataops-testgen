from unittest.mock import patch

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
