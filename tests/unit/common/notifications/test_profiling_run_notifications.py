from itertools import count
from unittest.mock import ANY, Mock, call, patch
from urllib.parse import quote

import pytest

from testgen.common.models.hygiene_issue import IssueCount
from testgen.common.models.notification_settings import (
    ProfilingRunNotificationSettings,
    ProfilingRunNotificationTrigger,
)
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.notifications.profiling_run import send_profiling_run_notifications

pytestmark = pytest.mark.unit


def create_ns(**kwargs):
    with patch("testgen.common.notifications.profiling_run.ProfilingRunNotificationSettings.save"):
        return ProfilingRunNotificationSettings.create("proj", None, **kwargs)


@pytest.fixture
def ns_select_result():
    return [
        create_ns(recipients=["always@example.com"], trigger=ProfilingRunNotificationTrigger.always),
        create_ns(recipients=["on_changes@example.com"], trigger=ProfilingRunNotificationTrigger.on_changes),
    ]


@pytest.fixture
def ns_select_patched(ns_select_result):
    with patch("testgen.common.notifications.profiling_run.ProfilingRunNotificationSettings.select") as mock:
        mock.return_value = ns_select_result
        yield mock


def create_hygiene_issue_list(length):
    priorities = ("Definite", "Likely", "Possible", "High", "Moderate")
    tr_list = []
    for idx in range(length):
        hi = Mock()
        priority = priorities[min(4, idx // 3)]
        hi.priority = priority
        hi.table_name = "table-name"
        hi.column_name = "col-name"
        hi.type_.name = "issue-type"
        hi.detail = "issue-detail"
        tr_list.append(hi)

    return tr_list


@pytest.fixture
def hi_select_mock():
    with patch("testgen.common.notifications.profiling_run.HygieneIssue.select_with_diff") as mock:
        yield mock


@pytest.fixture
def hi_count_mock():
    with patch("testgen.common.notifications.profiling_run.HygieneIssue.select_count_by_priority") as mock:
        yield mock



@pytest.fixture
def send_mock():
    with patch("testgen.common.notifications.profiling_run.ProfilingRunEmailTemplate.send") as mock:
        yield mock


@pytest.fixture
def get_prev_mock():
    with patch("testgen.common.notifications.profiling_run.ProfilingRun.get_previous") as mock:
        yield mock


@pytest.mark.parametrize(
    ("profiling_run_status", "has_prev_run", "issue_count", "new_issue_count", "expected_triggers"),
    (
        ("Error", True, 25, 0, ("always", "on_changes")),
        ("Error", True, 0, 0, ("always", "on_changes")),
        ("Cancelled", True, 50, 10, ("always", "on_changes")),
        ("Complete", True, 50, 10, ("always", "on_changes")),
        ("Complete", True, 15, 0, ("always",)),
        ("Complete", False, 15, 15, ("always", "on_changes")),
    ),
)
def test_send_profiling_run_notification(
    profiling_run_status,
    has_prev_run,
    issue_count,
    new_issue_count,
    expected_triggers,
    db_session_mock,
    ns_select_patched,
    get_prev_mock,
    hi_select_mock,
    hi_count_mock,
    send_mock,
):
    profiling_run = ProfilingRun(id="pr-id", table_groups_id="tg-id", status=profiling_run_status)
    get_prev_mock.return_value = ProfilingRun(id="pr-prev-id") if has_prev_run else None
    new_count = iter(count())
    priorities = ("Definite", "Likely", "Possible", "High", "Moderate")
    hi_list = [
        (hi, not has_prev_run or next(new_count) < new_issue_count)
        for hi in create_hygiene_issue_list(issue_count)
    ]
    hi_select_mock.return_value = hi_list[:20]
    hi_count_dict = {p: IssueCount() for p in priorities}
    for hi, _ in hi_list:
        hi_count_dict[hi.priority].total += 1
    hi_count_mock.return_value = hi_count_dict
    db_session_mock.execute().one.return_value = (
        ("project_name", "proj-name"),
        ("table_groups_name", "t-group-name"),
        ("table_group_schema", "t-group-schema"),
    )

    send_profiling_run_notifications(profiling_run)

    get_prev_mock.assert_called()
    ns_select_patched.assert_called_once_with(enabled=True, table_group_id="tg-id")
    hi_select_mock.assert_called_once_with("pr-id", "pr-prev-id" if has_prev_run else None, limit=20)
    hi_count_mock.assert_called_once_with("pr-id")

    send_mock.assert_has_calls(
        [
           call(
                ANY,
                {
                    "profiling_run": {
                        "id": "pr-id",
                        "issues_url": "http://tg-base-url/profiling-runs:hygiene?run_id=pr-id&source=email",
                        "results_url": "http://tg-base-url/profiling-runs:results?run_id=pr-id&source=email",
                        "start_time": None,
                        "end_time": None,
                        "status": profiling_run_status,
                        "log_message": None,
                        "table_ct": None,
                        "column_ct": None,
                    },
                    "issue_count": issue_count,
                    "hygiene_issues_summary": ANY,
                    "notification_trigger": trigger,
                    "project_name": "proj-name",
                    "table_groups_name": "t-group-name",
                    "table_group_schema": "t-group-schema",
                },
            )
            for trigger in expected_triggers
        ],
        any_order=True,
    )
    assert send_mock.call_count == len(expected_triggers)

    summary = send_mock.call_args_list[0].args[1]["hygiene_issues_summary"]

    assert len(summary) == len(priorities)
    assert sum(s["count"].total for s in summary) == issue_count
    assert sum(s["truncated"] for s in summary) == max(0, issue_count - 20)
    assert sum(len(s["issues"]) for s in summary) == min(issue_count, 20)
    assert all(s.get("label") is not None for s in summary)
    assert all(s.get("priority") in priorities for s in summary)
    assert all(s.get("url") is not None for s in summary)

    # Verify priority-to-likelihood URL mapping and URL encoding
    expected_likelihoods = {
        "Definite": "Definite",
        "Likely": "Likely",
        "Possible": "Possible",
        "High": "Potential PII",
        "Moderate": "Potential PII",
    }
    for s in summary:
        expected_likelihood = expected_likelihoods[s["priority"]]
        assert f"likelihood={quote(expected_likelihood)}" in s["url"]

    # Verify is_new flags are passed through
    all_issues = [issue for s in summary for issue in s["issues"]]
    if not has_prev_run:
        assert all(issue["is_new"] is True for issue in all_issues)
    elif new_issue_count == 0:
        assert all(issue["is_new"] is False for issue in all_issues)
