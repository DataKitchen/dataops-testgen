from itertools import count
from unittest.mock import ANY, Mock, call, patch
from urllib.parse import quote

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from testgen.common.enums import JOB_STATUS_LABEL, JobStatus
from testgen.common.models.hygiene_issue import IssueCount
from testgen.common.models.notification_settings import (
    ProfilingRunNotificationSettings,
    ProfilingRunNotificationTrigger,
)
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.notifications.profiling_run import (
    ProfilingRunEmailTemplate,
    send_profiling_run_notifications,
)

pytestmark = pytest.mark.unit


def make_job_execution(status, started_at=None, completed_at=None, error_message=None, active_seconds=None):
    return Mock(
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        error_message=error_message,
        active_seconds=active_seconds,
    )


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
        (JobStatus.ERROR, True, 25, 0, ("always", "on_changes")),
        (JobStatus.ERROR, True, 0, 0, ("always", "on_changes")),
        (JobStatus.CANCELED, True, 50, 10, ("always", "on_changes")),
        (JobStatus.COMPLETED, True, 50, 10, ("always", "on_changes")),
        (JobStatus.COMPLETED, True, 15, 0, ("always",)),
        (JobStatus.COMPLETED, False, 15, 15, ("always", "on_changes")),
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
    profiling_run = ProfilingRun(
        id="pr-id",
        table_groups_id="tg-id",
        project_code="proj",
    )
    profiling_run.job_execution = make_job_execution(profiling_run_status)
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
    db_session_mock.execute().mappings().one.return_value = {
        "project_name": "proj-name",
        "table_groups_name": "t-group-name",
        "table_group_schema": "t-group-schema",
        "sql_flavor_code": "postgresql",
    }

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
                        "issues_url": "http://tg-base-url/profiling-runs:hygiene?project_code=proj&run_id=pr-id&source=email",
                        "results_url": "http://tg-base-url/profiling-runs:results?project_code=proj&run_id=pr-id&source=email",
                        "start_time": None,
                        "end_time": None,
                        # Nothing worked was recorded, so there is no duration to report.
                        "duration_seconds": None,
                        "status": profiling_run_status,
                        "status_label": JOB_STATUS_LABEL[profiling_run_status],
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
                    "schema_label": "Schema",
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


# --- schema reporting per database type ---


def _webhook_context(schema_label):
    return {
        "profiling_run": {"status_label": "Completed"},
        "table_groups_name": "t-group-name",
        "table_group_schema": "main",
        "schema_label": schema_label,
        "issue_count": 0,
        "hygiene_issues_summary": [],
    }


def _email_context(schema_label):
    return {
        **_webhook_context(schema_label),
        "project_name": "proj-name",
        "notification_trigger": "always",
        "profiling_run": {
            "status": "completed",
            "status_label": "Completed",
            "table_ct": 1,
            "column_ct": 2,
            "start_time": None,
            "duration_seconds": None,
            "results_url": "http://tg/results",
            "issues_url": "http://tg/issues",
        },
    }


@pytest.mark.parametrize(
    ("sql_flavor_code", "expected_label"),
    (
        ("postgresql", "Schema"),
        ("salesforce_data360", "Data Space"),
        ("files", None),
    ),
)
def test_context_names_the_schema_the_way_the_database_type_does(
    sql_flavor_code,
    expected_label,
    db_session_mock,
    ns_select_patched,
    get_prev_mock,
    hi_select_mock,
    hi_count_mock,
    send_mock,
):
    profiling_run = ProfilingRun(id="pr-id", table_groups_id="tg-id", project_code="proj")
    profiling_run.job_execution = make_job_execution(JobStatus.COMPLETED)
    get_prev_mock.return_value = ProfilingRun(id="pr-prev-id")
    hi_select_mock.return_value = []
    hi_count_mock.return_value = {
        priority: IssueCount() for priority in ("Definite", "Likely", "Possible", "High", "Moderate")
    }
    db_session_mock.execute().mappings().one.return_value = {
        "project_name": "proj-name",
        "table_groups_name": "t-group-name",
        "table_group_schema": "main",
        "sql_flavor_code": sql_flavor_code,
    }

    send_profiling_run_notifications(profiling_run)

    context = send_mock.call_args.args[1]
    assert context["schema_label"] == expected_label
    assert context["table_group_schema"] == "main"


def test_the_labels_come_from_the_table_groups_own_connection(
    db_session_mock, ns_select_patched, get_prev_mock, hi_select_mock, hi_count_mock, send_mock
):
    """A project with several connections must still yield one row for the table group."""
    profiling_run = ProfilingRun(id="pr-id", table_groups_id="tg-id", project_code="proj")
    profiling_run.job_execution = make_job_execution(JobStatus.COMPLETED)
    get_prev_mock.return_value = ProfilingRun(id="pr-prev-id")
    hi_select_mock.return_value = []
    hi_count_mock.return_value = {
        priority: IssueCount() for priority in ("Definite", "Likely", "Possible", "High", "Moderate")
    }

    send_profiling_run_notifications(profiling_run)

    labels_sql = next(
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in (call.args[0] for call in db_session_mock.execute.call_args_list if call.args)
        if isinstance(statement, Select) and "connections" in str(statement)
    )
    assert "JOIN connections ON connections.connection_id = table_groups.connection_id" in labels_sql
    assert "connections.project_code" not in labels_sql


def test_email_omits_the_schema_row_when_the_database_type_names_none():
    body = str(ProfilingRunEmailTemplate().compiled_body(_email_context(None)))

    assert "Schema" not in body
    assert "main" not in body


def test_email_labels_the_schema_row_the_way_the_database_type_does():
    body = str(ProfilingRunEmailTemplate().compiled_body(_email_context("Data Space")))

    assert "Data Space" in body
    assert "main" in body


def test_webhook_payload_nulls_the_schema_when_the_database_type_names_none():
    """The key stays put, as every other value the payload may not have does."""
    payload = ProfilingRunEmailTemplate().webhook_data(_webhook_context(None))

    assert "schema" in payload
    assert payload["schema"] is None


def test_webhook_payload_carries_the_schema_when_the_database_type_names_one():
    payload = ProfilingRunEmailTemplate().webhook_data(_webhook_context("Data Space"))

    assert payload["schema"] == "main"
