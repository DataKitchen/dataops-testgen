"""Tests for the webhook envelope builder + Slack/Teams wrappers.

The generic envelope is the contract a receiver writes against; the wrappers make
Slack and Teams work by pasting a URL and nothing else. What matters:

- Envelope is JSON-serializable (any non-serializable value slipping in would
  crash delivery silently).
- Slack keeps a fallback ``text`` alongside blocks; a receiver rendering blocks
  falls back cleanly.
- Teams targets Adaptive Card v1.2 and stays under the 28 KB size cap.
"""

import json

import pytest

from testgen.common.models.notification_destinations import WebhookDestination, WebhookType
from testgen.common.notifications.webhook_payload import (
    MAX_SLACK_SECTION_CHARS,
    MAX_TEAMS_ENVELOPE_BYTES,
    SCHEMA_VERSION,
    build_envelope,
    wrap_for,
    wrap_slack,
    wrap_teams,
)

pytestmark = pytest.mark.unit


# ─── build_envelope ──────────────────────────────────────────────────


def test_envelope_carries_documented_top_level_keys():
    envelope = build_envelope(
        event_type="test_run",
        trigger="on_failures",
        project_code="P1",
        project_name="Project One",
        summary="Test Run Completed: X | 3 failures",
        url="https://example.com/tests",
    )
    assert envelope["schema_version"] == SCHEMA_VERSION
    assert envelope["event"] == "test_run"
    assert envelope["trigger"] == "on_failures"
    assert envelope["project"] == {"code": "P1", "name": "Project One"}
    assert envelope["summary"].startswith("Test Run")
    assert envelope["url"].startswith("https://")
    assert envelope["data"] == {}
    assert "delivery_id" in envelope
    assert "occurred_at" in envelope


def test_envelope_defaults_are_safe_strings_not_none():
    envelope = build_envelope(
        event_type="test_run",
        trigger=None,
        project_code=None,
        project_name=None,
        summary="",
        url=None,
    )
    assert envelope["trigger"] == ""
    assert envelope["project"] == {"code": "", "name": ""}
    assert envelope["url"] == ""


def test_envelope_is_json_serializable():
    envelope = build_envelope(
        event_type="test_run",
        trigger="always",
        project_code="P1",
        project_name="Project One",
        summary="short summary",
        url="https://example.com",
        data={"count": 3, "items": ["a", "b"]},
    )
    encoded = json.dumps(envelope)  # must not raise
    assert '"schema_version"' in encoded


def test_envelope_carries_supplied_delivery_id_when_given():
    envelope = build_envelope(
        event_type="test_run", trigger="always",
        project_code="P", project_name="P",
        summary="", url=None,
        delivery_id="fixed-uuid-value",
    )
    assert envelope["delivery_id"] == "fixed-uuid-value"


# ─── wrap_slack ──────────────────────────────────────────────────────


def _make_envelope(summary="short summary", url="https://tg/x"):
    return build_envelope(
        event_type="test_run", trigger="on_failures",
        project_code="P1", project_name="Project One",
        summary=summary, url=url,
    )


def test_slack_wrapper_keeps_text_as_fallback():
    payload = wrap_slack(_make_envelope())
    assert payload["text"] == "short summary"
    assert isinstance(payload["blocks"], list)
    assert payload["blocks"][0]["type"] == "section"


def test_slack_wrapper_truncates_section_text_over_the_slack_limit():
    long_summary = "x" * (MAX_SLACK_SECTION_CHARS + 500)
    payload = wrap_slack(_make_envelope(summary=long_summary))
    section_text = payload["blocks"][0]["text"]["text"]
    assert len(section_text) <= MAX_SLACK_SECTION_CHARS
    assert section_text.endswith("…")
    assert payload["text"] == long_summary  # unwrapped for fallback


def test_slack_wrapper_includes_project_and_url_in_context_block():
    payload = wrap_slack(_make_envelope())
    context_block = next(b for b in payload["blocks"] if b["type"] == "context")
    text = context_block["elements"][0]["text"]
    assert "Project One" in text
    assert "https://tg/x" in text


def test_slack_wrapper_escapes_only_slack_control_characters():
    envelope = _make_envelope(summary='Orders & Returns <EU> "daily"')
    envelope["project"]["name"] = "R&D"
    payload = wrap_slack(envelope)
    expected = 'Orders &amp; Returns &lt;EU&gt; "daily"'
    assert payload["text"] == expected
    assert payload["blocks"][0]["text"]["text"] == expected
    context_text = payload["blocks"][1]["elements"][0]["text"]
    assert context_text.startswith("*R&amp;D*")


# ─── wrap_teams ──────────────────────────────────────────────────────


def test_teams_wrapper_is_adaptive_card_v12_message_shape():
    payload = wrap_teams(_make_envelope())
    assert payload["type"] == "message"
    attachment = payload["attachments"][0]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
    card = attachment["content"]
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == "1.2"
    assert card["body"][0]["type"] == "TextBlock"
    assert card["body"][0]["text"] == "short summary"


def test_teams_wrapper_shrinks_body_to_stay_under_size_cap():
    huge = "x" * (MAX_TEAMS_ENVELOPE_BYTES + 2000)
    payload = wrap_teams(_make_envelope(summary=huge))
    encoded = json.dumps(payload, separators=(",", ":"))
    assert len(encoded.encode("utf-8")) <= MAX_TEAMS_ENVELOPE_BYTES


# ─── wrap_for dispatches on destination type ─────────────────────────


def _dest(webhook_type):
    return WebhookDestination(
        destination_type="webhook",
        config={"webhook_type": webhook_type.value if isinstance(webhook_type, WebhookType) else webhook_type},
    )


def test_wrap_for_slack_yields_blocks_shape():
    payload = wrap_for(_dest(WebhookType.slack), _make_envelope())
    assert "blocks" in payload


def test_wrap_for_teams_yields_attachment_shape():
    payload = wrap_for(_dest(WebhookType.microsoft_teams), _make_envelope())
    assert "attachments" in payload


def test_wrap_for_generic_returns_envelope_unchanged():
    envelope = _make_envelope()
    assert wrap_for(_dest(WebhookType.generic), envelope) is envelope
