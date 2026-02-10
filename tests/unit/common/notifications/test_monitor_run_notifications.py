from unittest.mock import Mock, patch

import pytest

from testgen.common.models.notification_settings import (
    MonitorNotificationSettings,
    MonitorNotificationTrigger,
)
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_result import TestResult
from testgen.common.models.test_run import TestRun
from testgen.common.notifications.monitor_run import send_monitor_notifications

pytestmark = pytest.mark.unit


def create_monitor_ns(**kwargs):
    with patch("testgen.common.notifications.monitor_run.MonitorNotificationSettings.save"):
        return MonitorNotificationSettings.create("proj", "tg-id", "ts-id", **kwargs)


def create_test_result(table_name, test_type, message, result_code=0):
    mock = Mock(spec=TestResult)
    mock.table_name = table_name
    mock.test_type = test_type
    mock.message = message
    mock.result_code = result_code
    return mock


@pytest.fixture
def ns_select_result():
    return [
        create_monitor_ns(
            recipients=["always@example.com"],
            trigger=MonitorNotificationTrigger.on_anomalies,
        ),
        create_monitor_ns(
            recipients=["filtered@example.com"],
            trigger=MonitorNotificationTrigger.on_anomalies,
            table_name="users",
        ),
    ]


@pytest.fixture
def ns_select_patched(ns_select_result):
    with patch("testgen.common.notifications.monitor_run.MonitorNotificationSettings.select") as mock:
        mock.return_value = ns_select_result
        yield mock


@pytest.fixture
def send_mock():
    with patch("testgen.common.notifications.monitor_run.MonitorEmailTemplate.send") as mock:
        yield mock


@pytest.fixture
def select_where_mock():
    with patch("testgen.common.notifications.monitor_run.TableGroup.select_where") as mock:
        yield mock


@pytest.fixture
def project_get_mock():
    with patch("testgen.common.notifications.monitor_run.Project.get") as mock:
        yield mock


@pytest.fixture
def test_result_select_where_mock():
    with patch("testgen.common.notifications.monitor_run.TestResult.select_where") as mock:
        yield mock


@pytest.fixture
def persisted_setting_mock():
    with patch("testgen.common.notifications.monitor_run.PersistedSetting.get") as mock:
        mock.return_value = "http://tg-base-url"
        yield mock


@pytest.mark.parametrize(
    (
        "freshness_count", "schema_count", "volume_count", "table_name_filter",
        "expected_send_calls", "expected_anomalies_count"
    ),
    [
        (0, 0, 0, None, 0, 0),
        (5, 0, 0, None, 1, 5),
        (0, 3, 0, None, 1, 3),
        (0, 0, 2, None, 1, 2),
        (5, 3, 2, None, 1, 10),
        (5, 3, 2, "users", 1, 10),
        (10, 5, 3, None, 1, 18),
    ]
)
def test_send_monitor_notifications(
        freshness_count,
        schema_count,
        volume_count,
        table_name_filter,
        expected_send_calls,
        expected_anomalies_count,
        ns_select_patched,
        select_where_mock,
        project_get_mock,
        test_result_select_where_mock,
        send_mock,
        persisted_setting_mock,
):
    test_run = TestRun(
        id="monitor-run-id",
        test_suite_id="monitor-suite-id",
        test_endtime="2024-01-15T10:30:00Z",
    )

    table_group = Mock(spec=TableGroup)
    table_group.id = "tg-id"
    table_group.project_code = "proj-code"
    table_group.table_groups_name = "production_tables"
    select_where_mock.return_value = [table_group]

    project = Mock(spec=Project)
    project.project_name = "Data Platform"
    project_get_mock.return_value = project

    test_results = []
    for _ in range(freshness_count):
        test_results.append(create_test_result("orders", "Freshness_Trend", "Data is 2 hours old"))
    for _ in range(schema_count):
        test_results.append(create_test_result("customers", "Schema_Drift", "Column 'status' was removed"))
    for _ in range(volume_count):
        test_results.append(create_test_result("products", "Volume_Trend", "Volume decreased by 25%"))

    test_result_select_where_mock.return_value = test_results

    if table_name_filter:
        ns_select_patched.return_value = [
            create_monitor_ns(
                recipients=["filtered@example.com"],
                trigger=MonitorNotificationTrigger.on_anomalies,
                table_name=table_name_filter,
            ),
        ]
    else:
        ns_select_patched.return_value = [
            create_monitor_ns(
                recipients=["always@example.com"],
                trigger=MonitorNotificationTrigger.on_anomalies,
            ),
        ]

    send_monitor_notifications(test_run)

    ns_select_patched.assert_called_once_with(
        enabled=True,
        test_suite_id="monitor-suite-id",
    )

    if expected_send_calls > 0:
        assert send_mock.call_count == expected_send_calls

        for call_args in send_mock.call_args_list:
            context = call_args[0][1]
            assert context["summary"]["test_endtime"] == "2024-01-15T10:30:00Z"
            assert context["summary"]["table_groups_name"] == "production_tables"
            assert context["summary"]["project_name"] == "Data Platform"
            assert context["total_anomalies"] == expected_anomalies_count
            assert "anomaly_counts" in context
            assert "anomalies" in context
            assert "view_in_testgen_url" in context
            assert len(context["anomalies"]) == expected_anomalies_count
    else:
        send_mock.assert_not_called()


@pytest.mark.parametrize(
    ("has_notifications", "has_table_group", "has_results"),
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ]
)
def test_send_monitor_notifications_early_exit(
        has_notifications,
        has_table_group,
        has_results,
        ns_select_patched,
        select_where_mock,
        test_result_select_where_mock,
        send_mock,
):
    test_run = TestRun(
        id="monitor-run-id",
        test_suite_id="monitor-suite-id",
        test_endtime="2024-01-15T10:30:00Z",
    )

    if not has_notifications:
        ns_select_patched.return_value = []
    if not has_table_group:
        select_where_mock.return_value = []
    if not has_results:
        test_result_select_where_mock.return_value = []

    send_monitor_notifications(test_run)

    send_mock.assert_not_called()


def test_send_monitor_notifications_anomaly_counts(
        ns_select_patched,
        select_where_mock,
        project_get_mock,
        test_result_select_where_mock,
        send_mock,
        persisted_setting_mock,
):
    test_run = TestRun(
        id="monitor-run-id",
        test_suite_id="monitor-suite-id",
        test_endtime="2024-01-15T10:30:00Z",
    )

    table_group = Mock(spec=TableGroup)
    table_group.id = "tg-id"
    table_group.project_code = "proj-code"
    table_group.table_groups_name = "prod"
    select_where_mock.return_value = [table_group]

    project = Mock(spec=Project)
    project.project_name = "Analytics"
    project_get_mock.return_value = project

    test_results = [
        create_test_result("t1", "Freshness_Trend", "msg1"),
        create_test_result("t2", "Freshness_Trend", "msg2"),
        create_test_result("t3", "Schema_Drift", "msg3"),
        create_test_result("t4", "Volume_Trend", "msg4"),
        create_test_result("t5", "Volume_Trend", "msg5"),
    ]
    test_result_select_where_mock.return_value = test_results

    ns_select_patched.return_value = [
        create_monitor_ns(
            recipients=["always@example.com"],
            trigger=MonitorNotificationTrigger.on_anomalies,
        ),
    ]

    send_monitor_notifications(test_run)

    assert send_mock.call_count == 1
    context = send_mock.call_args[0][1]

    anomaly_counts = {item["type"]: item["count"] for item in context["anomaly_counts"]}
    assert anomaly_counts["Freshness"] == 2
    assert anomaly_counts["Schema"] == 1
    assert anomaly_counts["Volume"] == 2


def test_send_monitor_notifications_url_construction(
        ns_select_patched,
        select_where_mock,
        project_get_mock,
        test_result_select_where_mock,
        send_mock,
        persisted_setting_mock,
):
    test_run = TestRun(
        id="monitor-run-id",
        test_suite_id="monitor-suite-id",
        test_endtime="2024-01-15T10:30:00Z",
    )

    table_group = Mock(spec=TableGroup)
    table_group.id = "tg-123"
    table_group.project_code = "proj-abc"
    table_group.table_groups_name = "prod"
    select_where_mock.return_value = [table_group]

    project = Mock(spec=Project)
    project.project_name = "Analytics"
    project_get_mock.return_value = project

    test_results = [create_test_result("orders", "Freshness_Trend", "stale")]
    test_result_select_where_mock.return_value = test_results

    # Test without table_name filter
    ns_select_patched.return_value = [
        create_monitor_ns(
            recipients=["always@example.com"],
            trigger=MonitorNotificationTrigger.on_anomalies,
        ),
    ]
    send_monitor_notifications(test_run)

    context = send_mock.call_args[0][1]
    assert context["view_in_testgen_url"] == (
        "http://tg-base-url/monitors?project_code=proj-abc&table_group_id=tg-123"
    )

    send_mock.reset_mock()
    ns_select_patched.return_value = [
        create_monitor_ns(
            recipients=["filtered@example.com"],
            trigger=MonitorNotificationTrigger.on_anomalies,
            table_name="users",
        ),
    ]

    send_monitor_notifications(test_run)

    context = send_mock.call_args[0][1]
    assert context["view_in_testgen_url"] == (
        "http://tg-base-url/monitors?project_code=proj-abc&table_group_id=tg-123&table_name_filter=users"
    )
    assert context["summary"]["table_name"] == "users"
