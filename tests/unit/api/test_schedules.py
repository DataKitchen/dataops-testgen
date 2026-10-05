"""Tests for testgen.api.schedules."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.errors import ForeignKeyViolation, UniqueViolation
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.schedules import router
from testgen.common.enums import JobKey
from testgen.common.models.scheduler import JobSchedule

pytestmark = pytest.mark.unit

MODULE = "testgen.api.schedules"
SCHEDULE_ID = uuid4()
TG_ID = uuid4()
TS_ID = uuid4()


def _client() -> TestClient:
    """A TestClient bypassing auth and db_session so routing and validation run unimpeded."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[db_session] = lambda: iter([None])
    app.dependency_overrides[get_authorized_user] = lambda: MagicMock(id=uuid4())
    return TestClient(app, raise_server_exceptions=False)


def _schedule(**overrides) -> JobSchedule:
    defaults = {
        "id": SCHEDULE_ID,
        "project_code": "demo",
        "key": JobKey.run_profile,
        "kwargs": {"table_group_id": str(TG_ID)},
        "cron_expr": "0 3 * * *",
        "cron_tz": "America/New_York",
        "active": True,
    }
    return JobSchedule(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

PROFILING_URL = f"/api/v1/table-groups/{TG_ID}/profiling-schedules"
TEST_RUN_URL = f"/api/v1/test-suites/{TS_ID}/test-run-schedules"


def _post(url: str, body: dict, *, permitted: bool = True, flush_error: Exception | None = None, parent=True):
    added: list[JobSchedule] = []

    def flush():
        if flush_error:
            raise flush_error
        added[-1].id = SCHEDULE_ID

    with (
        patch("testgen.api.deps.TableGroup") as mock_tg_cls,
        patch("testgen.api.deps.TestSuite") as mock_ts_cls,
        patch("testgen.api.deps.has_project_permission", return_value=permitted) as mock_perm,
        patch(f"{MODULE}.get_current_session") as mock_session,
    ):
        mock_tg_cls.get.return_value = MagicMock(id=TG_ID, project_code="demo") if parent else None
        mock_ts_cls.get_regular.return_value = MagicMock(id=TS_ID, project_code="demo") if parent else None
        mock_session.return_value.add.side_effect = added.append
        mock_session.return_value.flush.side_effect = flush
        resp = _client().post(url, json=body)
    return resp, added, mock_perm, mock_ts_cls


def _error_entries(resp) -> list[dict]:
    return resp.json()["detail"]["errors"]


def test_create_profiling_schedule_stores_a_run_profile_schedule():
    resp, added, _, _ = _post(PROFILING_URL, {"cron_expression": "0 3 * * *", "timezone": "America/New_York"})

    assert resp.status_code == 201
    [schedule] = added
    assert schedule.key == JobKey.run_profile
    assert schedule.kwargs == {"table_group_id": str(TG_ID)}
    assert (schedule.project_code, schedule.cron_expr, schedule.cron_tz, schedule.active) == (
        "demo", "0 3 * * *", "America/New_York", True,
    )
    body = resp.json()
    assert body["schedule_id"] == str(SCHEDULE_ID)
    assert body["kind"] == "profiling_run"
    assert body["table_group_id"] == str(TG_ID)
    assert body["test_suite_id"] is None
    assert body["description"] == "At 03:00"


def test_create_test_run_schedule_stores_a_run_tests_schedule():
    resp, added, _, _ = _post(TEST_RUN_URL, {"cron_expression": "30 6 * * 1"})

    assert resp.status_code == 201
    [schedule] = added
    assert schedule.key == JobKey.run_tests
    assert schedule.kwargs == {"test_suite_id": str(TS_ID)}
    body = resp.json()
    assert body["kind"] == "test_run"
    assert body["test_suite_id"] == str(TS_ID)
    assert body["table_group_id"] is None
    assert body["timezone"] == "UTC"


def test_create_schedule_stores_the_expression_in_canonical_form():
    resp, added, _, _ = _post(PROFILING_URL, {"cron_expression": "0  3 * * mon-fri"})

    assert added[0].cron_expr == "0 3 * * 1-5"
    assert resp.json()["cron_expression"] == "0 3 * * 1-5"


def test_create_schedule_reports_the_next_run_in_utc():
    resp, _, _, _ = _post(PROFILING_URL, {"cron_expression": "0 3 * * *", "timezone": "Asia/Tokyo"})

    next_run_at = datetime.fromisoformat(resp.json()["next_run_at"])
    assert next_run_at.utcoffset().total_seconds() == 0
    assert next_run_at.hour == 18  # 03:00 in Tokyo
    assert next_run_at > datetime.now(UTC)


def test_create_schedule_reports_every_validation_failure_without_storing():
    resp, added, _, _ = _post(PROFILING_URL, {"cron_expression": "", "timezone": "America/Argentina/ComodRivadavia"})

    assert resp.status_code == 400
    assert _error_entries(resp) == [
        {"code": "invalid_schedule", "detail": "`cron_expression` is required."},
        {"code": "invalid_schedule", "detail": "`timezone` must be at most 30 characters."},
    ]
    assert added == []


@pytest.mark.parametrize(
    ("cron_expression", "timezone"),
    [("61 * * * *", "UTC"), ("0 3 * * * *", "UTC"), ("0 0 31 2 *", "UTC"), ("0 3 * * *", "Mars/Base")],
)
def test_create_schedule_rejects_what_the_scheduler_cannot_run(cron_expression, timezone):
    resp, added, _, _ = _post(TEST_RUN_URL, {"cron_expression": cron_expression, "timezone": timezone})

    assert resp.status_code == 400
    assert _error_entries(resp)[0]["detail"].startswith("Invalid cron expression or timezone: ")
    assert added == []


def test_create_schedule_returns_409_for_an_identical_schedule():
    duplicate = IntegrityError("stmt", {}, UniqueViolation())

    resp, _, _, _ = _post(PROFILING_URL, {"cron_expression": "0 3 * * *"}, flush_error=duplicate)

    assert resp.status_code == 409
    assert _error_entries(resp)[0]["code"] == "duplicate_schedule"


def test_create_schedule_does_not_mask_other_integrity_errors():
    other = IntegrityError("stmt", {}, ForeignKeyViolation())

    resp, _, _, _ = _post(PROFILING_URL, {"cron_expression": "0 3 * * *"}, flush_error=other)

    assert resp.status_code == 500


@pytest.mark.parametrize(
    "body",
    [{}, {"timezone": "UTC"}, {"cron_expression": "0 3 * * *", "active": False},
     {"cron_expression": "0 3 * * *", "kwargs": {}}],
    ids=["empty", "no-cron", "active", "kwargs"],
)
def test_create_schedule_rejects_a_malformed_body(body):
    resp, added, _, _ = _post(PROFILING_URL, body)

    assert resp.status_code == 422
    assert added == []


@pytest.mark.parametrize("url", [PROFILING_URL, TEST_RUN_URL])
def test_create_schedule_asks_for_edit_permission(url):
    _, _, mock_perm, _ = _post(url, {"cron_expression": "0 3 * * *"})

    assert mock_perm.call_args.args[1:] == ("demo", "edit")


@pytest.mark.parametrize("url", [PROFILING_URL, TEST_RUN_URL])
def test_create_schedule_404_without_edit_permission(url):
    resp, added, _, _ = _post(url, {"cron_expression": "0 3 * * *"}, permitted=False)

    assert resp.status_code == 404
    assert added == []


def test_create_test_run_schedule_resolves_only_regular_suites():
    """A monitor suite's id reaches ``get_regular``, which returns None for it, so a monitor
    schedule cannot be created here."""
    resp, added, _, mock_ts_cls = _post(TEST_RUN_URL, {"cron_expression": "0 3 * * *"}, parent=False)

    assert resp.status_code == 404
    mock_ts_cls.get_regular.assert_called_once_with(TS_ID)
    mock_ts_cls.get.assert_not_called()
    assert added == []


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_get_schedule_returns_the_schedule():
    with (
        patch.object(JobSchedule, "get", return_value=_schedule()),
        patch("testgen.api.deps.has_project_permission", return_value=True) as mock_perm,
    ):
        resp = _client().get(f"/api/v1/schedules/{SCHEDULE_ID}")

    assert resp.status_code == 200
    assert resp.json()["schedule_id"] == str(SCHEDULE_ID)
    assert resp.json()["kind"] == "profiling_run"
    assert mock_perm.call_args.args[1:] == ("demo", "view")


def test_get_schedule_resolves_only_profiling_and_test_run_schedules():
    """Monitor and system schedules resolve as not found."""
    with (
        patch.object(JobSchedule, "get", return_value=None) as mock_get,
        patch("testgen.api.deps.has_project_permission", return_value=True),
    ):
        resp = _client().get(f"/api/v1/schedules/{SCHEDULE_ID}")

    assert resp.status_code == 404
    sql = " AND ".join(
        str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for clause in mock_get.call_args.args
    )
    assert f"job_schedules.id = '{SCHEDULE_ID}'" in sql
    assert "'run-profile'" in sql
    assert "'run-tests'" in sql
    assert "run-monitors" not in sql


def test_get_schedule_404_without_view_permission():
    with (
        patch.object(JobSchedule, "get", return_value=_schedule()),
        patch("testgen.api.deps.has_project_permission", return_value=False),
    ):
        assert _client().get(f"/api/v1/schedules/{SCHEDULE_ID}").status_code == 404


def test_paused_schedule_has_no_next_run():
    with (
        patch.object(JobSchedule, "get", return_value=_schedule(active=False)),
        patch("testgen.api.deps.has_project_permission", return_value=True),
    ):
        body = _client().get(f"/api/v1/schedules/{SCHEDULE_ID}").json()

    assert body["active"] is False
    assert body["next_run_at"] is None


def _list(query: str = "", *, permitted: bool = True):
    test_run = _schedule(id=uuid4(), key=JobKey.run_tests, kwargs={"test_suite_id": str(TS_ID)})
    with (
        patch.object(JobSchedule, "list_for_project", return_value=([_schedule(), test_run], 2)) as mock_list,
        patch("testgen.api.deps.has_project_permission", return_value=permitted) as mock_perm,
    ):
        resp = _client().get(f"/api/v1/projects/demo/schedules{query}")
    return resp, mock_list, mock_perm


def test_list_schedules_identifies_what_each_schedule_runs():
    resp, mock_list, _ = _list()

    assert resp.status_code == 200
    body = resp.json()
    assert (body["page"], body["limit"], body["total"]) == (1, 20, 2)
    assert [(item["kind"], item["table_group_id"], item["test_suite_id"]) for item in body["items"]] == [
        ("profiling_run", str(TG_ID), None),
        ("test_run", None, str(TS_ID)),
    ]
    assert mock_list.call_args.kwargs == {"key_filter": None, "page": 1, "limit": 20}


@pytest.mark.parametrize(("kind", "key"), [("profiling_run", JobKey.run_profile), ("test_run", JobKey.run_tests)])
def test_list_schedules_filters_by_kind(kind, key):
    _, mock_list, _ = _list(f"?kind={kind}")

    assert mock_list.call_args.kwargs["key_filter"] == [key]


@pytest.mark.parametrize("query", ["?kind=monitor", "?page=0", "?limit=101"])
def test_list_schedules_rejects_bad_query_values(query):
    resp, _, _ = _list(query)

    assert resp.status_code == 422


def test_list_schedules_asks_for_view_permission():
    _, _, mock_perm = _list()

    assert mock_perm.call_args.args[1:] == ("demo", "view")


def test_list_defaults_to_profiling_and_test_run_schedules_only():
    """``list_for_project`` without a key filter must not return monitor or system schedules."""
    session = MagicMock()
    session.scalar.return_value = 0
    session.scalars.return_value.all.return_value = []
    with patch("testgen.common.models.scheduler.get_current_session", return_value=session):
        JobSchedule.list_for_project("demo")

    query = session.scalars.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "'run-profile'" in sql
    assert "'run-tests'" in sql
    assert "run-monitors" not in sql
    assert "run-data-cleanup" not in sql
