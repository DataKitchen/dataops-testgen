"""Regression test for ``NotificationSettings.paginate_for_projects`` return shape.

``Entity._paginate`` returns ``RowMapping`` objects unless a ``data_class`` is
supplied. ``paginate_for_projects`` deliberately omits ``data_class`` -- it wants
polymorphic ORM instances, not a flat dataclass -- so it must unwrap the mapping
itself.

Getting this wrong is invisible on an empty project and a 500 on a populated one:
``api/notifications.list_rules`` feeds each row to ``_rule_to_response``, whose
first act is ``rule.notification_destination_id``. A ``RowMapping`` has no such
attribute, so the endpoint raises ``AttributeError`` for any project with at
least one rule. The schema-level tests could not catch it because they never
build a populated list.
"""

from unittest.mock import patch

import pytest

from testgen.common.models.notification_settings import (
    NotificationSettings,
    TestRunNotificationSettings,
    TestRunNotificationTrigger,
)

pytestmark = pytest.mark.unit


def _rule() -> TestRunNotificationSettings:
    return TestRunNotificationSettings(
        project_code="p",
        recipients=["a@x.co"],
        settings={"trigger": TestRunNotificationTrigger.always.value},
    )


def test_paginate_for_projects_returns_orm_instances_not_row_mappings():
    """Rows must be usable with ``isinstance`` dispatch and attribute access."""
    rule = _rule()
    # ``_paginate`` with no ``data_class`` hands back ``RowMapping``-shaped rows;
    # mimic that shape (a mapping whose single value is the entity) so the test
    # pins the unwrap rather than the SQL.
    fake_rows = [{"NotificationSettings": rule}]

    with patch.object(NotificationSettings, "_paginate", return_value=(fake_rows, 1)):
        rows, total = NotificationSettings.paginate_for_projects(["p"], page=1, limit=20)

    assert total == 1
    assert len(rows) == 1
    assert rows[0] is rule
    assert isinstance(rows[0], NotificationSettings)
    # The exact access ``_rule_addressing_out`` makes first.
    assert rows[0].notification_destination_id is None


def test_paginate_for_projects_empty_result_is_not_special_cased():
    with patch.object(NotificationSettings, "_paginate", return_value=([], 0)):
        rows, total = NotificationSettings.paginate_for_projects(["p"], page=1, limit=20)
    assert rows == []
    assert total == 0
