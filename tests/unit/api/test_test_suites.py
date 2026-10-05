"""Tests for testgen.api.test_suites."""

import inspect
import re
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.schemas import TestSuiteCreate
from testgen.api.test_suites import router
from testgen.common.enums import SuiteType
from testgen.common.models.test_suite import TestSuite, TestSuiteListItem

pytestmark = pytest.mark.unit

MODULE = "testgen.api.test_suites"
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
TS_ID = uuid4()
TG_ID = uuid4()
RUN_ID = uuid4()


def _client() -> TestClient:
    """A TestClient bypassing auth and db_session so routing and validation run unimpeded."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[db_session] = lambda: iter([None])
    app.dependency_overrides[get_authorized_user] = lambda: MagicMock(id=uuid4())
    return TestClient(app)


def _list_item(**overrides) -> TestSuiteListItem:
    defaults = {
        "id": TS_ID,
        "test_suite": "Orders",
        "project_code": "demo",
        "connection_id": 3,
        "table_groups_id": TG_ID,
        "table_groups_name": "client_42",
        "test_suite_description": "Order checks",
        "test_count": 12,
        "latest_run_id": RUN_ID,
        "latest_run_started_at": NOW,
        "latest_run_test_count": 12,
        "latest_run_passed_count": 9,
        "latest_run_failed_count": 1,
        "latest_run_warning_count": 1,
        "latest_run_error_count": 0,
        "latest_run_log_count": 0,
        "latest_run_dismissed_count": 1,
    }
    return TestSuiteListItem(**{**defaults, **overrides})


def _suite(**overrides):
    defaults = {
        "id": TS_ID,
        "test_suite": "Orders",
        "project_code": "demo",
        "connection_id": 3,
        "table_groups_id": TG_ID,
        "test_suite_description": None,
        "severity": None,
        "dq_score_exclude": False,
        "export_to_observability": False,
        "component_key": None,
        "component_type": "dataset",
        "component_name": None,
        "generation_sets": None,
        "suite_type": SuiteType.REGULAR,
    }
    return MagicMock(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.TestSuite")
def test_list_test_suites_renames_columns_for_the_consumer(mock_cls, _perm):
    mock_cls.list_for_project.return_value = ([_list_item()], 1)

    resp = _client().get("/api/v1/projects/demo/test-suites")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["page"], body["limit"], body["total"]) == (1, 20, 1)
    assert body["items"] == [{
        "test_suite_id": str(TS_ID),
        "test_suite_name": "Orders",
        "project_code": "demo",
        "connection_id": 3,
        "table_group_id": str(TG_ID),
        "table_group_name": "client_42",
        "description": "Order checks",
        "test_count": 12,
        "latest_run": {
            "job_execution_id": str(RUN_ID),
            "started_at": "2026-09-28T12:00:00Z",
            "test_count": 12,
            "result_counts": {"passed": 9, "failed": 1, "warning": 1, "error": 0, "log": 0, "dismissed": 1},
        },
    }]


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.TestSuite")
def test_list_test_suites_reports_no_latest_run_for_a_suite_never_run(mock_cls, _perm):
    mock_cls.list_for_project.return_value = ([_list_item(latest_run_id=None, latest_run_started_at=None)], 1)

    resp = _client().get("/api/v1/projects/demo/test-suites")

    assert resp.json()["items"][0]["latest_run"] is None


def _list_clauses(query: str):
    with (
        patch("testgen.api.deps.has_project_permission", return_value=True),
        patch.object(TestSuite, "list_for_project", return_value=([], 0)) as mock_list,
    ):
        resp = _client().get(f"/api/v1/projects/demo/test-suites{query}")
    return resp, mock_list


def _compiled(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_list_test_suites_turns_the_query_string_into_filters():
    resp, mock_list = _list_clauses(f"?table_group_id={TG_ID}&test_suite_name=Orders&page=2")

    assert resp.status_code == 200
    assert resp.json()["items"] == []
    args = mock_list.call_args.args
    assert args[0] == "demo"
    assert [_compiled(clause) for clause in args[1:]] == [
        f"test_suites.table_groups_id = '{TG_ID}'",
        "test_suites.test_suite = 'Orders'",
    ]
    assert mock_list.call_args.kwargs == {"page": 2, "limit": 20}


def test_list_test_suites_without_filters_passes_no_clauses():
    _, mock_list = _list_clauses("")

    assert mock_list.call_args.args == ("demo",)


@pytest.mark.parametrize("query", ["?page=0", "?limit=0", "?limit=101", "?table_group_id=not-a-uuid"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.TestSuite")
def test_list_test_suites_rejects_bad_query_values(mock_cls, _perm, query):
    mock_cls.list_for_project.return_value = ([], 0)

    assert _client().get(f"/api/v1/projects/demo/test-suites{query}").status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.TestSuite")
def test_list_test_suites_asks_for_view_permission(mock_cls, mock_perm):
    mock_cls.list_for_project.return_value = ([], 0)

    _client().get("/api/v1/projects/demo/test-suites")

    assert mock_perm.call_args.args[1:] == ("demo", "view")


@patch("testgen.api.deps.has_project_permission", return_value=False)
def test_list_test_suites_404_without_view_permission(_perm):
    assert _client().get("/api/v1/projects/demo/test-suites").status_code == 404


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def _get(suite, *, table_group=None, permitted: bool = True):
    with (
        patch("testgen.api.deps.TestSuite") as mock_deps_cls,
        patch("testgen.api.deps.has_project_permission", return_value=permitted) as mock_perm,
        patch(f"{MODULE}.TableGroup") as mock_tg_cls,
    ):
        mock_deps_cls.get_regular.return_value = suite
        mock_tg_cls.get.return_value = table_group
        resp = _client().get(f"/api/v1/test-suites/{TS_ID}")
    return resp, mock_deps_cls, mock_perm


def test_get_test_suite_returns_its_configuration():
    suite = _suite(
        test_suite_description="Order checks",
        severity="Warning",
        dq_score_exclude=True,
        export_to_observability=True,
        component_key="orders",
        component_name="Orders",
        generation_sets=["Standard"],
    )

    resp, _, _ = _get(suite, table_group=MagicMock(default_test_suite_id=TS_ID))

    assert resp.status_code == 200
    assert resp.json() == {
        "test_suite_id": str(TS_ID),
        "test_suite_name": "Orders",
        "project_code": "demo",
        "connection_id": 3,
        "table_group_id": str(TG_ID),
        "description": "Order checks",
        "default_severity": "warning",
        "exclude_from_quality_score": True,
        "export_to_observability": True,
        "component_key": "orders",
        "component_type": "dataset",
        "component_name": "Orders",
        "generation_sets": ["Standard"],
        "is_default": True,
    }


@pytest.mark.parametrize(("stored", "exposed"), [("Fail", "fail"), ("Warning", "warning"), ("Log", "log"), (None, None)])
def test_get_test_suite_lowercases_the_default_severity(stored, exposed):
    resp, _, _ = _get(_suite(severity=stored), table_group=MagicMock(default_test_suite_id=None))

    assert resp.json()["default_severity"] == exposed


def test_get_test_suite_is_not_default_when_its_table_group_points_elsewhere():
    resp, _, _ = _get(_suite(), table_group=MagicMock(default_test_suite_id=uuid4()))

    assert resp.json()["is_default"] is False
    assert resp.json()["generation_sets"] == []


def test_get_test_suite_resolves_only_regular_suites():
    """A monitor or contract suite's id reaches ``get_regular``, which returns None for it,
    so the caller gets the same 404 as for a suite that does not exist."""
    resp, mock_deps_cls, _ = _get(None)

    assert resp.status_code == 404
    mock_deps_cls.get_regular.assert_called_once_with(TS_ID)
    mock_deps_cls.get.assert_not_called()


def test_get_test_suite_asks_for_view_permission():
    _, _, mock_perm = _get(_suite(), table_group=MagicMock(default_test_suite_id=None))

    assert mock_perm.call_args.args[1:] == ("demo", "view")


def test_get_test_suite_404_without_view_permission():
    resp, _, _ = _get(_suite(), permitted=False)

    assert resp.status_code == 404


def test_get_test_suite_rejects_a_malformed_uuid():
    assert _client().get("/api/v1/test-suites/not-a-uuid").status_code == 422


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

CREATE_URL = f"/api/v1/table-groups/{TG_ID}/test-suites"


def _table_group(**overrides):
    defaults = {"id": TG_ID, "project_code": "demo", "connection_id": 3, "default_test_suite_id": None}
    return MagicMock(**{**defaults, **overrides})


def _assign_id(test_suite):
    test_suite.id = TS_ID


def _post(body: dict, *, table_group=None, permitted: bool = True, refresh=None):
    table_group = _table_group() if table_group is None else table_group
    with (
        patch("testgen.api.deps.TableGroup") as mock_tg_cls,
        patch("testgen.api.deps.has_project_permission", return_value=permitted) as mock_perm,
        patch.object(TestSuite, "save", autospec=True, side_effect=_assign_id) as mock_save,
        patch(f"{MODULE}.get_current_session") as mock_session,
        patch("testgen.common.generation_set_service.list_generation_sets", return_value=["Quick", "Standard"]),
    ):
        mock_tg_cls.get.return_value = table_group
        mock_session.return_value.refresh.side_effect = refresh
        resp = _client().post(CREATE_URL, json=body)
    return resp, mock_save, mock_perm, table_group


def _saved(mock_save) -> TestSuite:
    return mock_save.call_args.args[0]


def _error_entries(resp) -> list[dict]:
    return resp.json()["detail"]["errors"]


def test_create_test_suite_returns_201_with_the_server_assigned_id():
    resp, _, _, _ = _post({"test_suite_name": "Orders"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["test_suite_id"] == str(TS_ID)
    assert body["test_suite_name"] == "Orders"
    assert (body["project_code"], body["connection_id"], body["table_group_id"]) == ("demo", 3, str(TG_ID))


def test_create_test_suite_applies_defaults_to_omitted_fields():
    resp, mock_save, _, table_group = _post({"test_suite_name": "Orders"})

    saved = _saved(mock_save)
    assert saved.suite_type == SuiteType.REGULAR
    assert saved.export_to_observability is False
    assert saved.dq_score_exclude is False
    assert saved.severity is None
    assert saved.component_type == "dataset"
    assert saved.generation_sets is None
    assert resp.json()["is_default"] is False
    assert table_group.default_test_suite_id is None
    table_group.save.assert_not_called()


def test_create_test_suite_does_not_take_the_model_export_default():
    """``export_to_observability`` defaults to Y on the model; a create that omits it must not export."""
    resp, _, _, _ = _post({"test_suite_name": "Orders"})

    assert resp.json()["export_to_observability"] is False


def test_create_test_suite_strips_the_name():
    resp, mock_save, _, _ = _post({"test_suite_name": "  client_42  "})

    assert _saved(mock_save).test_suite == "client_42"
    assert resp.json()["test_suite_name"] == "client_42"


def test_create_test_suite_treats_null_as_omitted():
    resp, mock_save, _, table_group = _post({
        "test_suite_name": "Orders",
        "component_type": None,
        "export_to_observability": None,
        "exclude_from_quality_score": None,
        "set_as_default": None,
    })

    assert resp.status_code == 201
    saved = _saved(mock_save)
    assert saved.component_type == "dataset"
    assert saved.export_to_observability is False
    assert saved.dq_score_exclude is False
    table_group.save.assert_not_called()


def test_create_test_suite_applies_every_supplied_field():
    resp, mock_save, _, _ = _post({
        "test_suite_name": "Orders",
        "description": "Order checks",
        "default_severity": "fail",
        "exclude_from_quality_score": True,
        "export_to_observability": True,
        "component_key": "orders",
        "component_type": "table",
        "component_name": "Orders",
        "generation_sets": ["Standard", "Quick"],
    })

    assert resp.status_code == 201
    saved = _saved(mock_save)
    assert saved.test_suite_description == "Order checks"
    assert saved.severity == "Fail"
    assert saved.dq_score_exclude is True
    assert saved.export_to_observability is True
    assert (saved.component_key, saved.component_type, saved.component_name) == ("orders", "table", "Orders")
    assert saved.generation_sets == ["Standard", "Quick"]

    body = resp.json()
    assert body["default_severity"] == "fail"
    assert body["exclude_from_quality_score"] is True
    assert body["generation_sets"] == ["Standard", "Quick"]


def test_create_test_suite_set_as_default_points_the_table_group_at_it():
    resp, _, _, table_group = _post({"test_suite_name": "Orders", "set_as_default": True})

    assert resp.status_code == 201
    assert table_group.default_test_suite_id == TS_ID
    table_group.save.assert_called_once()
    assert resp.json()["is_default"] is True


def test_create_test_suite_set_as_default_replaces_an_existing_default():
    table_group = _table_group(default_test_suite_id=uuid4())

    resp, _, _, _ = _post({"test_suite_name": "Orders", "set_as_default": True}, table_group=table_group)

    assert table_group.default_test_suite_id == TS_ID
    assert resp.json()["is_default"] is True


def test_create_test_suite_responds_with_the_row_as_stored():
    def reload_as_stored(test_suite):
        test_suite.test_suite_description = None

    resp, _, _, _ = _post({"test_suite_name": "Orders", "description": ""}, refresh=reload_as_stored)

    assert resp.json()["description"] is None


def test_create_test_suite_reports_every_validation_failure():
    resp, mock_save, _, table_group = _post({
        "test_suite_name": " ",
        "component_key": "k" * 101,
        "generation_sets": ["Nope"],
        "set_as_default": True,
    })

    assert resp.status_code == 400
    entries = _error_entries(resp)
    assert {entry["code"] for entry in entries} == {"invalid_test_suite"}
    assert [entry["detail"] for entry in entries][:2] == [
        "`test_suite_name` is required.",
        "`component_key` must be at most 100 characters.",
    ]
    assert entries[2]["detail"].startswith("`generation_sets`: Unknown generation sets: Nope.")
    mock_save.assert_not_called()
    table_group.save.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"test_suite_name": "Orders", "test_suite_id": str(uuid4())},
        {"test_suite_name": "Orders", "suite_type": "monitor"},
        {"test_suite_name": "Orders", "project_code": "other"},
        {"test_suite_name": "Orders", "default_severity": "log"},
        {"test_suite_name": "Orders", "default_severity": "Fail"},
        {"test_suite_name": "Orders", "set_as_default": "yes"},
        {"test_suite_name": "Orders", "export_to_observability": 1},
        {"test_suite_name": "Orders", "generation_sets": "Standard"},
    ],
    ids=[
        "no-name", "caller-id", "suite-type", "caller-project", "log-severity", "db-cased-severity",
        "string-as-bool", "int-as-bool", "sets-not-a-list",
    ],
)
def test_create_test_suite_rejects_a_malformed_body(body):
    resp, mock_save, _, _ = _post(body)

    assert resp.status_code == 422
    mock_save.assert_not_called()


def test_create_test_suite_asks_for_edit_permission():
    _, _, mock_perm, _ = _post({"test_suite_name": "Orders"})

    assert mock_perm.call_args.args[1:] == ("demo", "edit")


def test_create_test_suite_404_without_edit_permission():
    resp, mock_save, _, _ = _post({"test_suite_name": "Orders"}, permitted=False)

    assert resp.status_code == 404
    mock_save.assert_not_called()


def test_every_create_field_is_handled_by_the_endpoint():
    """The endpoint maps each body field by hand, so a field added to the schema without a
    matching line in the endpoint would be accepted and then silently ignored."""
    from testgen.api.test_suites import create_test_suite

    source = inspect.getsource(create_test_suite)
    unhandled = [name for name in TestSuiteCreate.model_fields if f"body.{name}" not in source]

    assert unhandled == []


# ---------------------------------------------------------------------------
# the raw SELECT list must keep feeding the dataclass
# ---------------------------------------------------------------------------


def test_select_list_supplies_every_dataclass_field():
    """``list_for_project`` builds rows with ``TestSuiteListItem(**row)``, so a column dropped
    from the SELECT raises TypeError at runtime. Every other test here mocks the query."""
    source = inspect.getsource(TestSuite.list_for_project)
    start = source.index("        SELECT\n            suites.id,")
    select_list = source[start:source.index("        FROM test_suites AS suites\n", start)]

    missing = [
        field
        for field in TestSuiteListItem.__annotations__
        if not re.search(rf"\b{re.escape(field)}\b", select_list)
    ]

    assert not missing, f"not selected by the query: {missing}"
