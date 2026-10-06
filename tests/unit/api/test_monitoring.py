"""Tests for testgen.api.monitoring."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.monitoring import router
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.test_suite import PredictSensitivity

pytestmark = pytest.mark.unit

MODULE = "testgen.api.monitoring"
TG_ID = uuid4()
SUITE_ID = uuid4()
URL = f"/api/v1/table-groups/{TG_ID}/monitoring"


def _client() -> TestClient:
    """A TestClient bypassing auth and db_session so routing and validation run unimpeded."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[db_session] = lambda: iter([None])
    app.dependency_overrides[get_authorized_user] = lambda: MagicMock(id=uuid4())
    return TestClient(app, raise_server_exceptions=False)


def _suite(**overrides) -> MagicMock:
    defaults = {
        "id": SUITE_ID,
        "monitor_lookback": 14,
        "monitor_regenerate_freshness": True,
        "predict_min_lookback": 30,
        "predict_sensitivity": PredictSensitivity.medium,
        "predict_exclude_weekends": False,
        "holiday_codes_list": None,
    }
    return MagicMock(**{**defaults, **overrides})


def _schedule(**overrides) -> JobSchedule:
    defaults = {
        "id": uuid4(), "project_code": "demo", "key": "run-monitors", "kwargs": {"test_suite_id": str(SUITE_ID)},
        "cron_expr": "0 0,12 * * *", "cron_tz": "UTC", "active": True,
    }
    return JobSchedule(**{**defaults, **overrides})


def _call(method: str, body: dict | None = None, *, monitored: bool = True, permitted: bool = True, suite=None,
          schedule=None):
    suite = suite or _suite()
    schedule = schedule or _schedule()
    table_group = MagicMock(id=TG_ID, project_code="demo", monitor_test_suite_id=SUITE_ID if monitored else None)
    with (
        patch("testgen.api.deps.TableGroup") as mock_tg_cls,
        patch("testgen.api.deps.has_project_permission", return_value=permitted) as mock_perm,
        patch(f"{MODULE}.TestSuite") as mock_suite_cls,
        patch(f"{MODULE}.JobSchedule") as mock_schedule_cls,
        patch(f"{MODULE}.enable_monitoring", return_value=(suite, 2)) as mock_enable,
        patch(f"{MODULE}.update_monitoring") as mock_update,
        patch(f"{MODULE}.count_monitors", return_value=2),
        patch(f"{MODULE}.get_current_session"),
        patch("testgen.common.monitor_service.is_supported_holiday_code", side_effect=lambda c: c.upper() != "ZZ"),
    ):
        mock_tg_cls.get.return_value = table_group
        mock_suite_cls.get.return_value = suite if monitored else None
        mock_schedule_cls.get_for_monitor_suite.return_value = schedule
        resp = getattr(_client(), method)(URL, **({"json": body} if body is not None else {}))
    return resp, mock_enable, mock_update, mock_perm


def _errors(resp) -> list[dict]:
    return resp.json()["detail"]["errors"]


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


def test_get_monitoring_returns_settings_and_schedule():
    resp, _, _, mock_perm = _call("get", suite=_suite(holiday_codes_list=["US"]))

    assert resp.status_code == 200
    body = resp.json()
    assert body["table_group_id"] == str(TG_ID)
    assert body["monitor_count"] == 2
    assert (body["cron_expression"], body["timezone"], body["active"]) == ("0 0,12 * * *", "UTC", True)
    assert body["next_run_at"] is not None
    assert (body["lookback_runs"], body["min_training_lookback"], body["sensitivity"]) == (14, 30, "medium")
    assert body["holiday_codes"] == ["US"]
    assert mock_perm.call_args.args[1:] == ("demo", "view")


def test_get_monitoring_404_when_off():
    resp, _, _, _ = _call("get", monitored=False)

    assert resp.status_code == 404
    assert _errors(resp)[0]["code"] == "monitoring_not_enabled"


def test_get_monitoring_404_without_view_permission():
    resp, _, _, _ = _call("get", permitted=False)

    assert resp.status_code == 404
    assert _errors(resp)[0]["code"] == "not_found"


def test_paused_monitoring_has_no_next_run():
    resp, _, _, _ = _call("get", schedule=_schedule(active=False))

    assert resp.json()["active"] is False
    assert resp.json()["next_run_at"] is None


# ---------------------------------------------------------------------------
# PUT
# ---------------------------------------------------------------------------


def test_put_enables_monitoring_with_defaults_for_omitted_settings():
    resp, mock_enable, mock_update, _ = _call("put", {"cron_expression": "0 */12 * * *"}, monitored=False)

    assert resp.status_code == 201
    args, kwargs = mock_enable.call_args
    assert args[1:] == ("0 0,12 * * *", "UTC")
    assert kwargs["suite_attrs"] == {
        "monitor_lookback": 14,
        "monitor_regenerate_freshness": True,
        "predict_min_lookback": 30,
        "predict_sensitivity": "medium",
        "predict_exclude_weekends": False,
        "predict_holiday_codes": None,
    }
    mock_update.assert_not_called()


def test_put_applies_every_sent_setting():
    _, mock_enable, _, _ = _call("put", {
        "cron_expression": "0 6 * * *", "timezone": "America/New_York", "lookback_runs": 50,
        "regenerate_freshness": False, "min_training_lookback": 60, "sensitivity": "high",
        "exclude_weekends": True, "holiday_codes": ["us", "US", "xnys"],
    }, monitored=False)

    args, kwargs = mock_enable.call_args
    assert args[2] == "America/New_York"
    assert kwargs["suite_attrs"] == {
        "monitor_lookback": 50,
        "monitor_regenerate_freshness": False,
        "predict_min_lookback": 60,
        "predict_sensitivity": "high",
        "predict_exclude_weekends": True,
        "predict_holiday_codes": ["US", "XNYS"],
    }


def test_put_replaces_the_configuration_when_already_enabled():
    """A replace resets omitted settings to their defaults and does not regenerate monitors."""
    resp, mock_enable, mock_update, _ = _call("put", {"cron_expression": "0 6 * * *", "lookback_runs": 50})

    assert resp.status_code == 200
    mock_enable.assert_not_called()
    kwargs = mock_update.call_args.kwargs
    assert kwargs["cron_expr"] == "0 6 * * *"
    assert kwargs["cron_tz"] == "UTC"
    assert kwargs["suite_attrs"]["monitor_lookback"] == 50
    assert kwargs["suite_attrs"]["predict_sensitivity"] == "medium"
    assert kwargs["suite_attrs"]["predict_holiday_codes"] is None
    assert "active" not in kwargs or kwargs["active"] is None


def test_put_treats_null_settings_as_omitted():
    _, mock_enable, _, _ = _call("put", {"cron_expression": "0 6 * * *", "sensitivity": None, "timezone": None},
                                 monitored=False)

    assert mock_enable.call_args.args[2] == "UTC"
    assert mock_enable.call_args.kwargs["suite_attrs"]["predict_sensitivity"] == "medium"


def test_put_reports_every_problem_without_storing():
    resp, mock_enable, mock_update, _ = _call("put", {
        "cron_expression": "61 * * * *", "lookback_runs": 0, "min_training_lookback": 5, "holiday_codes": ["ZZ"],
    }, monitored=False)

    assert resp.status_code == 400
    details = [entry["detail"] for entry in _errors(resp)]
    assert {entry["code"] for entry in _errors(resp)} == {"invalid_monitoring"}
    assert details[0].startswith("Invalid cron expression or timezone:")
    assert details[1:3] == [
        "`lookback_runs` must be between 1 and 200.",
        "`min_training_lookback` must be between 20 and 1000.",
    ]
    assert details[3].startswith("`holiday_codes` has unknown codes: ZZ.")
    mock_enable.assert_not_called()
    mock_update.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [{}, {"cron_expression": "0 6 * * *", "active": False}, {"cron_expression": "0 6 * * *", "lookback_runs": "14"},
     {"cron_expression": "0 6 * * *", "sensitivity": "extreme"}],
    ids=["no-cron", "unknown-field", "string-as-int", "bad-sensitivity"],
)
def test_put_rejects_a_malformed_body(body):
    resp, mock_enable, _, _ = _call("put", body, monitored=False)

    assert resp.status_code == 422
    mock_enable.assert_not_called()


def test_put_asks_for_edit_permission():
    _, _, _, mock_perm = _call("put", {"cron_expression": "0 6 * * *"})

    assert mock_perm.call_args.args[1:] == ("demo", "edit")


def test_put_404_without_edit_permission():
    resp, mock_enable, mock_update, _ = _call("put", {"cron_expression": "0 6 * * *"}, permitted=False)

    assert resp.status_code == 404
    mock_enable.assert_not_called()
    mock_update.assert_not_called()


# ---------------------------------------------------------------------------
# PATCH
# ---------------------------------------------------------------------------


def test_patch_changes_only_the_sent_fields():
    resp, _, mock_update, _ = _call("patch", {"sensitivity": "low", "holiday_codes": ["gb"]})

    assert resp.status_code == 200
    kwargs = mock_update.call_args.kwargs
    assert kwargs["suite_attrs"] == {"predict_sensitivity": "low", "predict_holiday_codes": ["GB"]}
    assert kwargs["cron_expr"] is None
    assert kwargs["cron_tz"] is None


def test_patch_with_an_empty_holiday_list_clears_it():
    _, _, mock_update, _ = _call("patch", {"holiday_codes": []})

    assert mock_update.call_args.kwargs["suite_attrs"] == {"predict_holiday_codes": None}


def test_patch_validates_a_new_timezone_against_the_stored_expression():
    resp, _, mock_update, _ = _call("patch", {"timezone": "Mars/Base"})

    assert resp.status_code == 400
    assert "Unknown timezone `Mars/Base`" in _errors(resp)[0]["detail"]
    mock_update.assert_not_called()


def test_patch_stores_a_new_expression_canonically():
    _, _, mock_update, _ = _call("patch", {"cron_expression": "0  6 * * mon-fri"})

    assert mock_update.call_args.kwargs["cron_expr"] == "0 6 * * 1-5"


@pytest.mark.parametrize("body", [{"lookback_runs": None}, {"timezone": None}, {"unknown": 1}])
def test_patch_rejects_null_and_unknown_fields(body):
    resp, _, mock_update, _ = _call("patch", body)

    assert resp.status_code == 422
    mock_update.assert_not_called()


def test_patch_404_when_off():
    resp, _, mock_update, _ = _call("patch", {"sensitivity": "high"}, monitored=False)

    assert resp.status_code == 404
    assert _errors(resp)[0]["code"] == "monitoring_not_enabled"
    mock_update.assert_not_called()


def test_patch_asks_for_edit_permission():
    _, _, _, mock_perm = _call("patch", {"sensitivity": "high"})

    assert mock_perm.call_args.args[1:] == ("demo", "edit")
