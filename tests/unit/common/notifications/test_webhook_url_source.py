"""Tests for the ``source`` parameter on deep links carried in webhook payloads.

Notification bodies are authored for email, so the links they build say
``source=email``. A webhook delivery has to rewrite it, or every click arriving
from Slack or Teams is attributed to email.
"""

import pytest

from testgen.common.models.notification_destinations import WebhookType
from testgen.common.notifications.webhook_payload import retarget_url_source

pytestmark = pytest.mark.unit

SCORE_URL = (
    "http://localhost:8501/quality-dashboard:score-details"
    "?project_code=DEFAULT&definition_id=abc-123&source=email"
)


@pytest.mark.parametrize(
    ("webhook_type", "expected"),
    [
        (WebhookType.slack, "slack"),
        (WebhookType.microsoft_teams, "teams"),
        (WebhookType.generic, "webhook"),
        (None, "webhook"),
    ],
)
def test_source_names_the_delivery_channel(webhook_type, expected):
    assert f"source={expected}" in retarget_url_source(SCORE_URL, webhook_type)
    assert "source=email" not in retarget_url_source(SCORE_URL, webhook_type)


def test_other_parameters_survive():
    rewritten = retarget_url_source(SCORE_URL, WebhookType.slack)

    assert "project_code=DEFAULT" in rewritten
    assert "definition_id=abc-123" in rewritten


def test_a_url_without_a_source_parameter_gains_one():
    assert retarget_url_source("http://host/page?a=1", WebhookType.slack) == "http://host/page?a=1&source=slack"


def test_missing_url_is_left_alone():
    assert retarget_url_source(None, WebhookType.slack) is None
    assert retarget_url_source("", WebhookType.slack) == ""
