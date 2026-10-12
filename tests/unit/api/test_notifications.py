from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from testgen.api.notifications import update_destination, update_rule
from testgen.api.schemas import DestinationUpdate, RuleUpdate
from testgen.common.models.notification_destinations import EmailDestination
from testgen.common.models.notification_settings import MonitorNotificationSettings

pytestmark = pytest.mark.unit


def _error_code(excinfo: pytest.ExceptionInfo[HTTPException]) -> str:
    return excinfo.value.detail["errors"][0]["code"]


@pytest.mark.parametrize(("body", "code"), [
    ({}, "no_fields"),
    ({"clear_table_name": False}, "no_fields"),
    ({"enabled": None}, "null_field"),
    ({"table_name": "orders", "clear_table_name": True}, "conflicting_fields"),
])
def test_rule_update_refuses_a_body_it_cannot_apply_as_sent(body, code):
    rule = MagicMock(spec=MonitorNotificationSettings)

    with pytest.raises(HTTPException) as excinfo:
        update_rule(rule=rule, body=RuleUpdate.model_validate(body))

    assert excinfo.value.status_code == 422
    assert _error_code(excinfo) == code
    rule.save.assert_not_called()


@pytest.mark.parametrize(("body", "code"), [
    ({"type": "email"}, "no_fields"),
    ({"type": "email", "name": None}, "null_field"),
])
def test_destination_update_refuses_a_body_it_cannot_apply_as_sent(body, code):
    destination = MagicMock(spec=EmailDestination)

    with pytest.raises(HTTPException) as excinfo:
        update_destination(destination=destination, body=DestinationUpdate.model_validate(body))

    assert excinfo.value.status_code == 422
    assert _error_code(excinfo) == code
    destination.save.assert_not_called()
