import uuid
from unittest.mock import ANY, Mock, call, patch

import pytest

from testgen.common.models.notification_settings import TestRunNotificationSettings, TestRunNotificationTrigger
from testgen.common.models.test_result import TestResultStatus
from testgen.common.models.test_run import TestRun
from testgen.common.notifications.test_run import send_test_run_notifications


def create_ns(**kwargs):
    with patch("testgen.common.notifications.test_run.TestRunNotificationSettings.save"):
        return TestRunNotificationSettings.create("proj", None, **kwargs)


def create_diff(failed=0, error=0, warning=0):
    return [
        (TestResultStatus.Passed, status, [uuid.uuid4() for _ in range(count)])
        for status, count in (
            (TestResultStatus.Failed, failed),
            (TestResultStatus.Warning, warning),
            (TestResultStatus.Error, error),
        )
        if count > 0
    ]


def create_test_result_list(length):
    tr_list = []
    for idx in range(length):
        mock = Mock()
        mock._as_dict.return_value = {
            "table_name": "tr-table",
            "column_names": "tr-columns",
            "message": f"tr-message-{idx}",
            "is_new": True,
            "test_type": "tr-type",
        }
        tr_list.append(mock)

    return tr_list


@pytest.fixture
def ns_select_result():
    return [
        create_ns(recipients=["always@example.com"], trigger=TestRunNotificationTrigger.always),
        create_ns(recipients=["on_failures@example.com"], trigger=TestRunNotificationTrigger.on_failures),
        create_ns(recipients=["on_warnings@example.com"], trigger=TestRunNotificationTrigger.on_warnings),
        create_ns(recipients=["on_changes@example.com"], trigger=TestRunNotificationTrigger.on_changes),
    ]


@pytest.fixture
def ns_select_patched(ns_select_result):
    with patch("testgen.common.notifications.test_run.TestRunNotificationSettings.select") as mock:
        mock.return_value = ns_select_result
        yield mock


@pytest.fixture
def send_mock():
    with patch("testgen.common.notifications.test_run.TestRunEmailTemplate.send") as mock:
        yield mock


@pytest.fixture
def get_prev_mock():
    with patch("testgen.common.notifications.test_run.TestRun.get_previous") as mock:
        yield mock


@pytest.fixture
def diff_mock():
    with patch("testgen.common.notifications.test_run.TestResult.diff") as mock:
        yield mock


@pytest.fixture
def select_mock():
    with patch("testgen.common.notifications.test_run.select") as mock:
        yield mock


@pytest.fixture
def select_summary_mock():
    with patch("testgen.common.notifications.test_run.TestRun.select_summary") as mock:
        yield mock



@pytest.mark.parametrize(
    (
        "test_run_status", "failed_ct", "warning_ct", "error_ct", "diff_mock_args",
        "failed_expected", "warning_expected", "error_expected", "expected_triggers"
    ),
    [
        ("Complete", 0, 0, 0, {}, 0, 0, 0, ["always"]),
        ("Complete", 1, 1, 1, {}, 1, 1, 1, ["always", "on_failures", "on_warnings"]),
        ("Complete", 50, 50, 50, {"failed": 2, "warning": 3}, 10, 5, 5, [
            "always", "on_failures", "on_warnings", "on_changes",
        ]),
        ("Complete", 0, 0, 50, {"error": 50}, 0, 0, 20, ["always", "on_failures", "on_warnings", "on_changes"]),
        ("Complete", 50, 0, 0, None, 20, 0, 0, ["always", "on_failures", "on_warnings"]),
        ("Complete", 50, 0, 10, {"failed": 5}, 15, 0, 5, ["always", "on_failures", "on_warnings", "on_changes"]),
        ("Error", 0, 0, 0, {}, 0, 0, 0, ["always", "on_failures", "on_warnings", "on_changes"]),
        ("Error", 20, 10, 0, None, 15, 5, 0, ["always", "on_failures", "on_warnings", "on_changes"]),
        ("Cancelled", 0, 0, 0, {}, 0, 0, 0, ["always", "on_failures", "on_warnings", "on_changes"]),
        ("Cancelled", 30, 20, 0, {}, 15, 5, 0, ["always", "on_failures", "on_warnings", "on_changes"]),
    ]
)
def test_send_test_run_notification(
        test_run_status,
        failed_ct,
        warning_ct,
        error_ct,
        diff_mock_args,
        failed_expected,
        warning_expected,
        error_expected,
        expected_triggers,
        ns_select_patched,
        get_prev_mock,
        diff_mock,
        send_mock,
        db_session_mock,
        select_mock,
        select_summary_mock,
):

    test_run = TestRun(
        id="tr-id",
        status=test_run_status,
        test_suite_id="ts-id",
        failed_ct=failed_ct,
        warning_ct=warning_ct,
        error_ct=error_ct,
    )

    db_session_mock.execute.side_effect = [
        [{} for _ in range(ct)]
        for ct in (failed_expected, warning_expected, error_expected)
        if ct > 0
    ]
    if diff_mock_args is None:
        get_prev_mock.return_value = None
    else:
        diff_mock.return_value = create_diff(**diff_mock_args)
        get_prev_mock.return_value = TestRun(id="tr-prev-id")
    summary = object()
    select_summary_mock.return_value = [summary]

    send_test_run_notifications(test_run)

    ns_select_patched.assert_called_once_with(enabled=True, test_suite_id="ts-id")

    if diff_mock_args is None:
        diff_mock.assert_not_called()
    else:
        diff_mock.assert_called_once_with("tr-prev-id", "tr-id")

    select_mock.assert_has_calls(
        [
            call().join().where().order_by().limit(ct)
            for ct in (failed_expected, warning_expected, error_expected)
            if ct > 0
        ],
        any_order=True,
    )

    expected_context = {
        "test_run": summary,
        "test_run_url": "http://tg-base-url/test-runs:results?run_id=tr-id",
        "test_run_id": "tr-id",
        "test_result_summary": ANY,
    }

    send_mock.assert_has_calls(
        [
            call(
                ANY,
                {**expected_context, "notification_trigger": trigger}
            )
            for trigger in expected_triggers
        ],
    )
    assert send_mock.call_count == len(expected_triggers)

    test_result_summary = list(send_mock.mock_calls[0].args[1]["test_result_summary"])
    for status, total, expected in (
        (TestResultStatus.Failed, failed_ct, failed_expected),
        (TestResultStatus.Warning, warning_ct, warning_expected),
        (TestResultStatus.Error, error_ct, error_expected),
    ):
        if expected:
            result_list = test_result_summary.pop(0)
            assert result_list["status"] == status.value
            assert result_list["label"]
            assert result_list["truncated"] == total - expected
            assert result_list["total"] == total
            assert len(result_list["result_list"]) == expected
    assert not test_result_summary
