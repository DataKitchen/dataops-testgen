"""Webhook payload assembly.

Every triggered rule produces a single documented envelope; three envelope shapes
carry the same facts to Slack, Microsoft Teams, or a generic receiver. Payload
values are always plain-Python (str/int/list/dict/None); no ORM objects, no HTML
markup, no CSS may reach the wire -- the ORM and email-template context are not
JSON-serializable and are held elsewhere.

The generic envelope is the documented contract a receiver writes against. The
Slack and Teams envelopes wrap it so both surfaces work by pasting a URL and
nothing else.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from testgen.common.models.notification_destinations import WebhookDestination, WebhookType

SCHEMA_VERSION = "1.0"
MAX_SLACK_SECTION_CHARS = 3000
MAX_TEAMS_ENVELOPE_BYTES = 28 * 1024


# The ``source`` query parameter on a deep link records which channel the reader
# arrived from. Notification bodies are authored for email, so the links they
# carry say ``email``; a webhook delivery rewrites it to name its own channel.
WEBHOOK_URL_SOURCES: dict[WebhookType, str] = {
    WebhookType.slack: "slack",
    WebhookType.microsoft_teams: "teams",
    WebhookType.generic: "webhook",
}


def retarget_url_source(url: str | None, webhook_type: WebhookType | None) -> str | None:
    """Return ``url`` with its ``source`` parameter naming the webhook channel.

    A URL without a ``source`` parameter gains one. An unrecognized webhook type
    falls back to ``webhook``.
    """
    if not url:
        return url
    source = WEBHOOK_URL_SOURCES.get(webhook_type, "webhook")
    parts = urlsplit(url)
    params = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "source"]
    params.append(("source", source))
    return urlunsplit(parts._replace(query=urlencode(params)))


def build_envelope(
    *,
    event_type: str,
    trigger: str | None,
    project_code: str | None,
    project_name: str | None,
    summary: str,
    url: str | None,
    data: dict[str, Any] | None = None,
    delivery_id: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """Build the documented generic payload for one triggered rule.

    Values coerce to safe defaults so a missing input never surfaces as ``None``
    where the schema documents a string.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "event": event_type,
        "trigger": trigger or "",
        "occurred_at": occurred_at or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "delivery_id": delivery_id or str(uuid4()),
        "project": {
            "code": project_code or "",
            "name": project_name or "",
        },
        "summary": summary,
        "url": url or "",
        "data": data or {},
    }


def wrap_for(destination: WebhookDestination, envelope: dict[str, Any]) -> dict[str, Any]:
    """Return the body to POST for ``destination``'s webhook type."""
    webhook_type = destination.webhook_type or WebhookType.generic
    if webhook_type == WebhookType.slack:
        return wrap_slack(envelope)
    if webhook_type == WebhookType.microsoft_teams:
        return wrap_teams(envelope)
    return envelope


def wrap_slack(envelope: dict[str, Any]) -> dict[str, Any]:
    """Wrap the generic envelope in Slack Block Kit.

    The ``text`` field is the notification fallback that Slack must always have;
    the blocks carry the same facts. Section text is truncated to Slack's per-block
    limit so a long summary does not fail the delivery.
    """
    summary = _slack_escape(envelope["summary"])
    trimmed = summary if len(summary) <= MAX_SLACK_SECTION_CHARS else summary[: MAX_SLACK_SECTION_CHARS - 1] + "…"
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": trimmed}},
    ]
    context_line = _slack_context_line(envelope)
    if context_line:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": context_line}]})
    return {"text": summary, "blocks": blocks}


def wrap_teams(envelope: dict[str, Any]) -> dict[str, Any]:
    """Wrap the generic envelope in the Adaptive Card v1.2 shape Power Automate accepts.

    Card body is capped so the total envelope stays under Teams' 28 KB limit.
    """
    body: list[dict[str, Any]] = [
        {"type": "TextBlock", "text": envelope["summary"], "wrap": True, "weight": "Bolder"},
    ]
    context_line = _teams_context_line(envelope)
    if context_line:
        body.append({"type": "TextBlock", "text": context_line, "wrap": True, "isSubtle": True, "size": "Small"})

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.2",
        "body": body,
    }
    envelope_body = {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card},
        ],
    }
    return _shrink_to_size_cap(envelope_body)


def _slack_context_line(envelope: dict[str, Any]) -> str:
    project_name = envelope["project"]["name"] or envelope["project"]["code"]
    parts = [f"*{_slack_escape(project_name)}*"] if project_name else []
    url = envelope.get("url")
    if url:
        parts.append(f"<{url}|Open in TestGen>")
    return " · ".join(parts)


def _slack_escape(text: str) -> str:
    """Escape the three characters Slack reserves for its own markup, and no others."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _teams_context_line(envelope: dict[str, Any]) -> str:
    project_name = envelope["project"]["name"] or envelope["project"]["code"]
    parts = [project_name] if project_name else []
    url = envelope.get("url")
    if url:
        parts.append(f"[Open in TestGen]({url})")
    return " · ".join(parts)


def _shrink_to_size_cap(body: dict[str, Any]) -> dict[str, Any]:
    """Trim card body until the JSON-encoded envelope fits under the Teams cap.

    Trims the summary text first, then any remaining blocks (context line, etc.)
    one by one, then drops tail blocks whole. Guaranteed to return an envelope
    under the cap: as an absolute last resort the body is replaced by a single
    marker block so the POST still carries a valid Adaptive Card rather than
    landing over-cap and being rejected by Power Automate.
    """

    def encoded_size() -> int:
        return len(json.dumps(body, separators=(",", ":")).encode("utf-8"))

    if encoded_size() <= MAX_TEAMS_ENVELOPE_BYTES:
        return body

    card_body = body["attachments"][0]["content"]["body"]

    # Trim the first block's text (typically the summary) first, then any others
    # (context line, etc.). Both are shrunk before any block is dropped.
    for block in card_body:
        _shrink_text_of(block, encoded_size)
        if encoded_size() <= MAX_TEAMS_ENVELOPE_BYTES:
            return body

    # Still over: drop tail blocks whole while more than one remains.
    while encoded_size() > MAX_TEAMS_ENVELOPE_BYTES and len(card_body) > 1:
        card_body.pop()

    # Absolute last resort: replace the body with a single marker so JSON stays valid.
    if encoded_size() > MAX_TEAMS_ENVELOPE_BYTES:
        body["attachments"][0]["content"]["body"] = [
            {"type": "TextBlock", "text": "TestGen notification (payload truncated)", "wrap": True}
        ]
    return body


def _shrink_text_of(block: dict[str, Any], encoded_size) -> None:
    text = block.get("text", "")
    if not text:
        return
    while encoded_size() > MAX_TEAMS_ENVELOPE_BYTES and len(text) > 1:
        overshoot = encoded_size() - MAX_TEAMS_ENVELOPE_BYTES
        step = max(overshoot, 32)
        text = text[: max(0, len(text) - step)]
        block["text"] = text + "…" if text else "…"
