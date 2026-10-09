"""Tests for testgen.api.table_groups."""

import re
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from testgen.api.deps import db_session, get_authorized_user
from testgen.api.schemas import CatalogTags, TableGroupCreate
from testgen.api.table_groups import get_table_group, list_table_groups, router
from testgen.common.database.table_group_service import SchemaMove, SchemaMoveRefused
from testgen.common.models.table_group import TableGroup

pytestmark = pytest.mark.unit

MODULE = "testgen.api.table_groups"
RULES_MODULE = "testgen.common.database.table_group_service"
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
TG_ID = uuid4()


@pytest.fixture(autouse=True)
def target_connection():
    """The connection the detail response reads to name the schema.

    Defaults to a database type that reports one, so tests saying nothing about the flavor see
    the stored value.
    """
    connection = MagicMock()
    connection.sql_flavor = "postgresql"
    connection.sql_flavor_code = "postgresql"
    with patch(f"{RULES_MODULE}.Connection.get_by_table_group", return_value=connection):
        yield connection


def _row(**overrides):
    defaults = {
        "id": TG_ID,
        "table_groups_name": "sales",
        "table_group_schema": "public",
        "sql_flavor_code": "postgresql",
        "project_code": "demo",
        "connection_id": 3,
        "connection_name": "Prod",
        "table_count": 12,
        "column_count": 140,
        "row_count": 98000,
        "last_profiled_date": NOW,
        "last_tested_date": None,
        "profiling_score": 0.95,
        "testing_score": 0.9,
        "quality_score": 0.855,
    }
    return MagicMock(**{**defaults, **overrides})


def _table_group(**overrides):
    defaults = {
        "id": TG_ID,
        "table_groups_name": "sales",
        "table_group_schema": "public",
        "project_code": "demo",
        "connection_id": 3,
        "default_test_suite_id": None,
        "monitor_test_suite_id": uuid4(),
        "last_complete_profile_run_id": uuid4(),
        "dq_score_profiling": 0.95,
        "dq_score_testing": 0.9,
        "description": "Sales tables",
        "profiling_table_set": None,
        "profiling_include_mask": "sales_%, orders_%",
        "profiling_exclude_mask": "%_tmp",
        "profile_id_column_mask": "%id",
        "profile_sk_column_mask": "%_sk",
        "profile_use_sampling": True,
        "profile_sample_percent": 30,
        "profile_sample_min_count": 100000,
        "profiling_delay_days": 0,
        "profile_flag_cdes": True,
        "profile_flag_pii": True,
        "profile_exclude_xde": True,
        "include_in_dashboard": True,
        "data_source": "CRM",
        "source_system": "Salesforce",
        "source_process": "nightly sync",
        "data_location": "us-east-1",
        "business_domain": "Revenue",
        "stakeholder_group": "Finance",
        "transform_level": "Curated",
        "data_product": "Sales Mart",
        "data_classification": "Internal",
    }
    return MagicMock(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_renames_columns_for_the_consumer(mock_cls):
    mock_cls.list_for_project.return_value = ([_row()], 1)

    item = list_table_groups(project_code="demo", page=1, limit=20).items[0]

    assert item.table_group_id == TG_ID
    assert item.table_group_name == "sales"
    assert item.schema_name == "public"
    assert item.last_profiled_at == NOW
    assert item.last_tested_at is None


@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_carries_connection_id(mock_cls):
    """The create path in a follow-on call addresses the connection, not its name."""
    mock_cls.list_for_project.return_value = ([_row()], 1)

    assert list_table_groups(project_code="demo", page=1, limit=20).items[0].connection_id == 3


@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_reports_counts_and_scores(mock_cls):
    mock_cls.list_for_project.return_value = ([_row()], 1)

    item = list_table_groups(project_code="demo", page=1, limit=20).items[0]

    assert (item.table_count, item.column_count, item.row_count) == (12, 140, 98000)
    assert (item.profiling_score, item.testing_score, item.quality_score) == (0.95, 0.9, 0.855)


@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_passes_idempotency_filters_through(mock_cls):
    """schema_name + table_group_name together answer "already set up?" in one call."""
    mock_cls.list_for_project.return_value = ([], 0)

    list_table_groups(
        project_code="demo",
        connection_id=3,
        schema_name="client_42",
        table_group_name="client_42_tables",
        page=1,
        limit=20,
    )

    mock_cls.list_for_project.assert_called_once_with(
        "demo",
        connection_id=3,
        schema_name="client_42",
        table_group_name="client_42_tables",
        page=1,
        limit=20,
    )


@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_empty_result_is_the_envelope_not_a_404(mock_cls):
    mock_cls.list_for_project.return_value = ([], 0)

    result = list_table_groups(project_code="demo", schema_name="absent", page=1, limit=20)

    assert (result.items, result.total, result.page, result.limit) == ([], 0, 1, 20)


# ---------------------------------------------------------------------------
# detail
# ---------------------------------------------------------------------------


def test_get_table_group_reports_configuration():
    result = get_table_group(_table_group())

    assert result.table_group_id == TG_ID
    assert result.table_group_name == "sales"
    assert result.schema_name == "public"
    assert result.connection_id == 3
    assert result.profile_id_column_mask == "%id"


def test_get_table_group_splits_the_comma_separated_criteria():
    """Stored as one delimited string; the parts are what a caller acts on, and a
    part can never contain a comma because nothing escapes one."""
    result = get_table_group(_table_group(
        profiling_table_set="orders, customers",
        profiling_include_mask="sales_%, orders_%",
        profiling_exclude_mask="%_tmp",
    ))

    assert result.table_set == ["orders", "customers"]
    assert result.include_masks == ["sales_%", "orders_%"]
    assert result.exclude_masks == ["%_tmp"]


def test_get_table_group_reports_unset_criteria_as_empty_lists():
    """An absent criterion is an empty list, never null, so a caller iterates without
    a null check and ``[]`` reads as 'no restriction'."""
    result = get_table_group(_table_group(
        profiling_table_set=None, profiling_include_mask=None, profiling_exclude_mask=None,
    ))

    assert (result.table_set, result.include_masks, result.exclude_masks) == ([], [], [])


def test_single_column_masks_stay_scalar():
    """Unlike the table criteria, these are never split — one pattern each."""
    result = get_table_group(_table_group(
        profile_id_column_mask="%id", profile_sk_column_mask="%_sk",
    ))

    assert result.profile_id_column_mask == "%id"
    assert result.profile_sk_column_mask == "%_sk"


def test_get_table_group_reports_sampling_as_numbers_and_booleans():
    result = get_table_group(_table_group())

    assert result.profile_use_sampling is True
    assert result.profile_sample_percent == 30
    assert result.profile_sample_min_count == 100000
    assert result.profiling_delay_days == 0


def test_get_table_group_groups_every_catalog_tag():
    """The tags are the Quality Score's slice axes and change nothing operationally,
    so they sit apart from the configuration that does."""
    result = get_table_group(_table_group())

    assert result.catalog_tags.model_dump() == {
        "data_source": "CRM",
        "source_system": "Salesforce",
        "source_process": "nightly sync",
        "data_location": "us-east-1",
        "business_domain": "Revenue",
        "stakeholder_group": "Finance",
        "transform_level": "Curated",
        "data_product": "Sales Mart",
        "data_classification": "Internal",
    }


def test_every_catalog_tag_names_a_real_column():
    """``CatalogTags`` is filled by attribute name, so a renamed column would return
    null for that tag rather than failing. The fixture is a MagicMock and would keep
    supplying the old name, so only this pins it."""
    from testgen.common.models.table_group import TableGroup

    assert set(CatalogTags.model_fields) <= set(TableGroup.__table__.columns.keys())


def test_catalog_tags_are_not_also_flat_on_the_response():
    exposed = set(get_table_group(_table_group()).model_dump())

    assert "catalog_tags" in exposed
    assert not exposed & {"data_source", "business_domain", "data_classification"}


def test_catalog_tags_stay_present_when_a_table_group_is_untagged():
    """Always present, so a client never handles both an absent key and a null one."""
    untagged = _table_group(**dict.fromkeys(
        ["data_source", "source_system", "source_process", "data_location", "business_domain",
         "stakeholder_group", "transform_level", "data_product", "data_classification"], None))

    tags = get_table_group(untagged).catalog_tags

    assert set(tags.model_dump()) == set(CatalogTags.model_fields)
    assert not any(tags.model_dump().values())


def test_get_table_group_withholds_unaddressable_ids_and_raw_scores():
    """The monitor suite and profile run key have no endpoint behind them here."""
    exposed = set(get_table_group(_table_group()).model_dump())

    assert not exposed & {
        "monitor_test_suite_id",
        "last_complete_profile_run_id",
        "dq_score_profiling",
        "dq_score_testing",
    }


# ---------------------------------------------------------------------------
# the filter predicates the listing builds
# ---------------------------------------------------------------------------


def _scope(**filters):
    """Capture the scope SQL and params TableGroup.list_for_project builds."""
    from testgen.common.models.table_group import TableGroup

    with patch.object(TableGroup, "_list_with_activity", return_value=([], 0)) as mock_list:
        TableGroup.list_for_project("demo", **filters)
    return mock_list.call_args.kwargs


def test_list_for_project_scopes_to_the_project_when_unfiltered():
    scope = _scope()

    assert scope["scope_sql"] == "groups.project_code = :project_code"
    assert scope["scope_params"] == {"project_code": "demo"}


def test_list_for_project_filters_match_exactly_not_by_pattern():
    """Schema and table names are case-sensitive on some flavors, so no ILIKE."""
    scope = _scope(schema_name="Client_42", table_group_name="Client_42_tables")

    assert "LIKE" not in scope["scope_sql"].upper()
    assert scope["scope_sql"] == (
        "groups.project_code = :project_code"
        " AND groups.table_group_schema = :table_group_schema"
        " AND groups.table_groups_name = :table_groups_name"
    )
    assert scope["scope_params"] == {
        "project_code": "demo",
        "table_group_schema": "Client_42",
        "table_groups_name": "Client_42_tables",
    }


def test_list_for_project_binds_filter_values_as_parameters():
    """Values reach raw SQL, so they must bind rather than interpolate."""
    scope = _scope(schema_name="'; DROP TABLE table_groups; --")

    assert "DROP TABLE" not in scope["scope_sql"]
    assert scope["scope_params"]["table_group_schema"] == "'; DROP TABLE table_groups; --"


def test_list_for_project_combines_connection_and_name_filters():
    scope = _scope(connection_id=3, table_group_name="sales")

    assert scope["scope_sql"] == (
        "groups.project_code = :project_code"
        " AND groups.connection_id = :connection_id"
        " AND groups.table_groups_name = :table_groups_name"
    )
    assert scope["scope_params"] == {"project_code": "demo", "connection_id": 3, "table_groups_name": "sales"}


# ---------------------------------------------------------------------------
# HTTP layer — routes, query bounds, and the permission the resolvers enforce
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    """A TestClient bypassing auth and db_session so routing and validation run unimpeded."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[db_session] = lambda: iter([None])
    app.dependency_overrides[get_authorized_user] = lambda: MagicMock(id=uuid4())
    return TestClient(app)


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_route_is_reachable(mock_cls, _perm):
    mock_cls.list_for_project.return_value = ([_row()], 1)

    resp = _client().get("/api/v1/projects/DEFAULT/table-groups")

    assert resp.status_code == 200
    assert resp.json()["items"][0]["schema_name"] == "public"


@pytest.mark.parametrize("query", ["?page=0", "?limit=0", "?limit=101"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_rejects_out_of_range_pagination(mock_cls, _perm, query):
    mock_cls.list_for_project.return_value = ([], 0)

    assert _client().get(f"/api/v1/projects/DEFAULT/table-groups{query}").status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_reads_filters_from_the_query_string(mock_cls, _perm):
    mock_cls.list_for_project.return_value = ([], 0)

    _client().get(
        "/api/v1/projects/DEFAULT/table-groups"
        "?schema_name=client_42&table_group_name=client_42_tables&connection_id=3"
    )

    assert mock_cls.list_for_project.call_args.kwargs == {
        "connection_id": 3,
        "schema_name": "client_42",
        "table_group_name": "client_42_tables",
        "page": 1,
        "limit": 20,
    }


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_rejects_a_non_integer_connection_filter(mock_cls, _perm):
    mock_cls.list_for_project.return_value = ([], 0)

    resp = _client().get("/api/v1/projects/DEFAULT/table-groups?connection_id=abc")

    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission")
@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_asks_for_view_permission(mock_cls, mock_perm):
    mock_cls.list_for_project.return_value = ([], 0)
    mock_perm.return_value = True

    _client().get("/api/v1/projects/DEFAULT/table-groups")

    assert mock_perm.call_args.args[2] == "view"


@patch("testgen.api.deps.TableGroup")
@patch("testgen.api.deps.has_project_permission", return_value=False)
def test_get_table_group_404_without_view_permission(_perm, mock_deps_cls):
    mock_deps_cls.get.return_value = _table_group()

    assert _client().get(f"/api/v1/table-groups/{TG_ID}").status_code == 404


def test_get_table_group_rejects_a_malformed_uuid():
    assert _client().get("/api/v1/table-groups/not-a-uuid").status_code == 422


# ---------------------------------------------------------------------------
# the raw SELECT list must keep feeding the dataclass
# ---------------------------------------------------------------------------


def _select_list() -> str:
    """The outer SELECT list of the listing query, excluding its CTEs and joins."""
    import inspect

    from testgen.common.models.table_group import TableGroup

    source = inspect.getsource(TableGroup._list_with_activity)
    start = source.index("\n        SELECT\n") + len("\n        SELECT\n")
    end = source.index("\n        FROM table_groups AS groups")
    return source[start:end]


def test_activity_timestamps_come_from_job_executions():
    """``test_runs.test_starttime`` is timestamp-without-zone while the profiling side
    reads the zone-aware ``job_executions.started_at``. Taking it directly would make
    ``last_tested_at`` the only naive timestamp the API serves."""
    select_list = _select_list()

    assert "test_starttime" not in select_list
    assert "latest_test.started_at AS last_tested_date" in select_list
    assert "latest_profile.started_at AS last_profiled_date" in select_list


def test_select_list_supplies_every_dataclass_field():
    """``_list_with_activity`` builds rows with ``TableGroupListItem(**row)``, so a column
    dropped from the SELECT raises TypeError at runtime. Every other test in this module
    mocks the query, so nothing else would catch it."""
    from testgen.common.models.table_group import TableGroupListItem

    select_list = _select_list()
    missing = [
        field
        for field in TableGroupListItem.__annotations__
        if not re.search(rf"\b{re.escape(field)}\b", select_list)
    ]

    assert not missing, f"selected by the query but not: {missing}"


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

CONNECTION = MagicMock(project_code="demo", connection_id=3, sql_flavor_code="postgresql")
CREATE_URL = "/api/v1/connections/3/table-groups"


def _assign_id(table_group, **_kwargs):
    table_group.id = TG_ID


def _post(body: dict, *, permitted: bool = True, connection=CONNECTION, refresh=None):
    with (
        patch("testgen.api.deps.Connection") as mock_conn_cls,
        patch("testgen.api.deps.has_project_permission", return_value=permitted) as mock_perm,
        patch.object(TableGroup, "save", autospec=True, side_effect=_assign_id) as mock_save,
        patch(f"{MODULE}.get_current_session") as mock_session,
    ):
        mock_conn_cls.get.return_value = connection
        mock_session.return_value.refresh.side_effect = refresh
        resp = _client().post(CREATE_URL, json=body)
    return resp, mock_save, mock_perm


def _saved(mock_save) -> TableGroup:
    return mock_save.call_args.args[0]


def _error_entries(resp) -> list[dict]:
    return resp.json()["detail"]["errors"]


def test_create_table_group_returns_201_with_the_server_assigned_id():
    resp, _, _ = _post({"table_group_name": "client_42", "schema_name": "client_42"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["table_group_id"] == str(TG_ID)
    assert body["table_group_name"] == "client_42"
    assert body["schema_name"] == "client_42"
    assert body["project_code"] == "demo"
    assert body["connection_id"] == 3


def test_create_table_group_applies_model_defaults_to_omitted_fields():
    resp, mock_save, _ = _post({"table_group_name": "client_42", "schema_name": "client_42"})

    body = resp.json()
    assert body["profile_id_column_mask"] == "%id"
    assert body["profile_sk_column_mask"] == "%_sk"
    assert body["profile_use_sampling"] is False
    assert body["profile_sample_percent"] == 30
    assert body["profile_sample_min_count"] == 100000
    assert body["profiling_delay_days"] == 0
    assert body["profile_flag_cdes"] is True
    assert body["profile_flag_pii"] is True
    assert body["profile_exclude_xde"] is True
    assert body["include_in_dashboard"] is True
    assert body["include_masks"] == []
    assert mock_save.call_args.kwargs == {"add_scorecard_definition": True}


def test_create_table_group_treats_null_as_omitted():
    resp, _, _ = _post({
        "table_group_name": "client_42",
        "schema_name": "client_42",
        "profile_sample_percent": None,
        "profile_flag_pii": None,
    })

    assert resp.status_code == 201
    assert resp.json()["profile_sample_percent"] == 30
    assert resp.json()["profile_flag_pii"] is True


def test_create_table_group_applies_every_supplied_field():
    resp, mock_save, _ = _post({
        "table_group_name": "client_42",
        "schema_name": "client_42",
        "description": "Client 42 onboarding",
        "table_set": ["orders", "customers"],
        "include_masks": ["fact_%", "dim_%"],
        "exclude_masks": ["tmp%"],
        "profile_id_column_mask": "%_id",
        "profile_sk_column_mask": "%_key",
        "profile_use_sampling": True,
        "profile_sample_percent": 10,
        "profile_sample_min_count": 5000,
        "profiling_delay_days": 2,
        "profile_flag_cdes": False,
        "profile_flag_pii": False,
        "profile_exclude_xde": False,
        "include_in_dashboard": False,
        "catalog_tags": {"data_source": "Snowflake", "business_domain": "Claims"},
        "add_scorecard": False,
    })

    assert resp.status_code == 201
    saved = _saved(mock_save)
    assert saved.profiling_table_set == "orders,customers"
    assert saved.profiling_include_mask == "fact_%,dim_%"
    assert saved.profiling_exclude_mask == "tmp%"
    assert saved.data_source == "Snowflake"
    assert saved.business_domain == "Claims"
    assert saved.source_system is None
    assert mock_save.call_args.kwargs == {"add_scorecard_definition": False}

    body = resp.json()
    assert body["description"] == "Client 42 onboarding"
    assert body["table_set"] == ["orders", "customers"]
    assert body["include_masks"] == ["fact_%", "dim_%"]
    assert body["exclude_masks"] == ["tmp%"]
    assert body["profile_id_column_mask"] == "%_id"
    assert body["profile_sk_column_mask"] == "%_key"
    assert body["profile_use_sampling"] is True
    assert body["profile_sample_percent"] == 10
    assert body["profile_sample_min_count"] == 5000
    assert body["profiling_delay_days"] == 2
    assert body["profile_flag_cdes"] is False
    assert body["profile_flag_pii"] is False
    assert body["profile_exclude_xde"] is False
    assert body["include_in_dashboard"] is False
    assert body["catalog_tags"]["data_source"] == "Snowflake"
    assert body["catalog_tags"]["business_domain"] == "Claims"


def test_create_table_group_reports_every_validation_failure():
    resp, mock_save, _ = _post({
        "table_group_name": "ab",
        "schema_name": " ",
        "profile_sample_percent": 0,
        "profiling_delay_days": -1,
    })

    assert resp.status_code == 400
    assert _error_entries(resp) == [
        {"code": "invalid_table_group", "detail": "`table_group_name` must be between 3 and 40 characters."},
        {"code": "invalid_table_group", "detail": "`schema_name` is required."},
        {"code": "invalid_table_group", "detail": "`profiling_delay_days` must be a non-negative integer."},
        {"code": "invalid_table_group", "detail": "`profile_sample_percent` must be between 1 and 100."},
    ]
    mock_save.assert_not_called()


def test_create_table_group_responds_with_the_row_as_stored():
    """The 201 body is built after the saved row is reloaded, so it matches a later GET:
    the column type stores an empty string as NULL."""
    def reload_as_stored(table_group):
        table_group.description = None
        table_group.data_source = None

    resp, _, _ = _post(
        {
            "table_group_name": "client_42",
            "schema_name": "client_42",
            "description": "",
            "catalog_tags": {"data_source": ""},
        },
        refresh=reload_as_stored,
    )

    assert resp.status_code == 201
    assert resp.json()["description"] is None
    assert resp.json()["catalog_tags"]["data_source"] is None


def test_create_table_group_rejects_values_wider_than_their_columns():
    resp, mock_save, _ = _post({
        "table_group_name": "client_42",
        "schema_name": "client_42",
        "table_set": [f"client_table_{i:03d}" for i in range(120)],
        "catalog_tags": {"business_domain": "x" * 41},
        "profiling_delay_days": 3_000_000_000,
    })

    assert resp.status_code == 400
    assert [entry["detail"] for entry in _error_entries(resp)] == [
        "`table_set` must be at most 2000 characters in total, counting a comma between entries.",
        "`business_domain` must be at most 40 characters.",
        f"`profiling_delay_days` must be at most {2**31 - 1}.",
    ]
    mock_save.assert_not_called()


def test_create_table_group_rejects_a_files_connection():
    files_connection = MagicMock(project_code="demo", connection_id=3, sql_flavor_code="files")

    resp, mock_save, _ = _post({"table_group_name": "client_42", "schema_name": "main"}, connection=files_connection)

    assert resp.status_code == 400
    assert _error_entries(resp)[0]["code"] == "unsupported_connection"
    mock_save.assert_not_called()


def _integrity_error(message: str) -> IntegrityError:
    return IntegrityError("stmt", {}, Exception(message))


def test_create_table_group_returns_409_on_a_duplicate_name():
    duplicate = _integrity_error('duplicate key value violates unique constraint "table_groups_name_unique"')
    with (
        patch("testgen.api.deps.Connection") as mock_conn_cls,
        patch("testgen.api.deps.has_project_permission", return_value=True),
        patch.object(TableGroup, "save", side_effect=duplicate),
        patch(f"{MODULE}.get_current_session"),
    ):
        mock_conn_cls.get.return_value = CONNECTION
        resp = _client().post(CREATE_URL, json={"table_group_name": "client_42", "schema_name": "client_42"})

    assert resp.status_code == 409
    assert _error_entries(resp)[0]["code"] == "duplicate_table_group_name"


def test_create_table_group_does_not_mask_other_integrity_errors():
    other = _integrity_error('violates foreign key constraint "table_groups_connections_fk"')
    with (
        patch("testgen.api.deps.Connection") as mock_conn_cls,
        patch("testgen.api.deps.has_project_permission", return_value=True),
        patch.object(TableGroup, "save", side_effect=other),
        patch(f"{MODULE}.get_current_session"),
        pytest.raises(IntegrityError),
    ):
        mock_conn_cls.get.return_value = CONNECTION
        _client().post(CREATE_URL, json={"table_group_name": "client_42", "schema_name": "client_42"})


@pytest.mark.parametrize(
    "body",
    [
        {"table_group_name": "client_42"},
        {"schema_name": "client_42"},
        {"table_group_name": "client_42", "schema_name": "client_42", "table_group_id": str(uuid4())},
        {"table_group_name": "client_42", "schema_name": "client_42", "project_code": "other"},
        {"table_group_name": "client_42", "schema_name": "client_42", "profile_sample_percnt": 10},
        {"table_group_name": "client_42", "schema_name": "client_42", "profile_sample_percent": True},
        {"table_group_name": "client_42", "schema_name": "client_42", "profile_sample_percent": "10"},
        {"table_group_name": "client_42", "schema_name": "client_42", "profile_use_sampling": "yes"},
        {"table_group_name": "client_42", "schema_name": "client_42", "include_masks": "fact_%"},
    ],
    ids=[
        "no-schema", "no-name", "caller-id", "caller-project", "unknown-field",
        "bool-as-int", "string-as-int", "string-as-bool", "mask-not-a-list",
    ],
)
def test_create_table_group_rejects_a_malformed_body(body):
    resp, mock_save, _ = _post(body)

    assert resp.status_code == 422
    mock_save.assert_not_called()


def test_create_table_group_asks_for_edit_permission():
    _, _, mock_perm = _post({"table_group_name": "client_42", "schema_name": "client_42"})

    assert mock_perm.call_args.args[1:] == ("demo", "edit")


def test_create_table_group_404_without_edit_permission():
    resp, mock_save, _ = _post({"table_group_name": "client_42", "schema_name": "client_42"}, permitted=False)

    assert resp.status_code == 404
    mock_save.assert_not_called()


def test_create_table_group_404_for_an_unknown_connection():
    resp, mock_save, _ = _post({"table_group_name": "client_42", "schema_name": "client_42"}, connection=None)

    assert resp.status_code == 404
    mock_save.assert_not_called()


def test_every_create_field_names_a_table_group_column_or_is_handled_by_the_endpoint():
    """The endpoint sets body fields onto the model by name, so a field added to the
    schema without a matching column would be set as a plain attribute and never saved."""
    from testgen.api.table_groups import _LIST_COLUMNS

    handled = {"table_group_name", "schema_name", "catalog_tags", "add_scorecard", *_LIST_COLUMNS}
    columns = set(TableGroup.__table__.columns.keys())

    assert set(TableGroupCreate.model_fields) - handled <= columns


# --- Schema reported per database type ---------------------------------------


@patch(f"{MODULE}.TableGroup")
def test_list_reports_no_schema_for_a_type_that_has_none(mock_cls):
    """The stored value is the engine's own default schema, not one the user chose."""
    mock_cls.list_for_project.return_value = ([_row(sql_flavor_code="files", table_group_schema="main")], 1)

    item = list_table_groups(project_code="demo", page=1, limit=20).items[0]

    assert item.schema_name is None


@patch(f"{MODULE}.TableGroup")
def test_list_reports_the_stored_value_for_a_type_that_names_one(mock_cls):
    mock_cls.list_for_project.return_value = ([_row(sql_flavor_code="salesforce_data360")], 1)

    item = list_table_groups(project_code="demo", page=1, limit=20).items[0]

    assert item.schema_name == "public"


def test_detail_reports_no_schema_for_a_type_that_has_none(target_connection):
    target_connection.sql_flavor = "duckdb"
    target_connection.sql_flavor_code = "files"

    response = get_table_group(table_group=_table_group(table_group_schema="main"))

    assert response.schema_name is None


# --- PATCH /table-groups/{id} ---


def _move(previous="public", schema="onboard_2026_09_16", missing=None, repointed=3):
    return SchemaMove(
        previous_schema=previous,
        schema=schema,
        missing_tables=missing or [],
        definitions_repointed=repointed,
    )


@patch(f"{MODULE}.apply_schema_move")
@patch(f"{MODULE}.move_table_group_schema")
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_update_table_group_moves_the_schema_and_reports_what_moved(
    mock_cls, _perm, mock_move, mock_apply,
):
    """The caller needs the tables the new schema lacks: their tests fail validation on the next test run."""
    mock_cls.get.return_value = _table_group()
    mock_move.return_value = _move(missing=["archive"])

    resp = _client().patch(
        f"/api/v1/table-groups/{TG_ID}", json={"schema_name": "onboard_2026_09_16"}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_change"]["previous_schema_name"] == "public"
    assert body["schema_change"]["missing_tables"] == ["archive"]
    assert body["schema_change"]["definitions_repointed"] == 3
    mock_apply.assert_called_once()


@patch(f"{MODULE}.apply_schema_move")
@patch(f"{MODULE}.move_table_group_schema")
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_update_table_group_resending_the_current_schema_moves_nothing(
    mock_cls, _perm, mock_move, mock_apply,
):
    mock_cls.get.return_value = _table_group(table_group_schema="public")

    resp = _client().patch(f"/api/v1/table-groups/{TG_ID}", json={"schema_name": "public"})

    assert resp.status_code == 200
    assert resp.json()["schema_change"] is None
    mock_move.assert_not_called()
    mock_apply.assert_not_called()


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_update_table_group_rejects_an_empty_body(mock_cls, _perm):
    """An empty patch would report success having changed nothing."""
    mock_cls.get.return_value = _table_group()

    assert _client().patch(f"/api/v1/table-groups/{TG_ID}", json={}).status_code == 422


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        ("job_in_flight", 409),
        ("schema_empty", 422),
        ("schema_unreadable", 422),
        ("schema_unsupported", 422),
        ("invalid_schema_name", 422),
    ],
)
@patch(f"{MODULE}.move_table_group_schema")
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_update_table_group_maps_each_refusal_to_its_status(
    mock_cls, _perm, mock_move, reason, status,
):
    """A job still running is a conflict the caller can retry; the rest are the request's fault."""
    mock_cls.get.return_value = _table_group()
    mock_move.side_effect = SchemaMoveRefused(reason, "nope")

    resp = _client().patch(
        f"/api/v1/table-groups/{TG_ID}", json={"schema_name": "onboard_2026_09_16"}
    )

    assert resp.status_code == status


@pytest.mark.parametrize("schema_name", ['x" OR 1=1--', "x`y", "a'b", "a\nb", "a" * 51])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_update_table_group_rejects_a_schema_that_would_end_the_quoting(mock_cls, _perm, schema_name):
    mock_cls.get.return_value = _table_group()

    resp = _client().patch(f"/api/v1/table-groups/{TG_ID}", json={"schema_name": schema_name})

    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_update_table_group_rejects_an_unknown_field(mock_cls, _perm):
    """A field this endpoint does not take yet would otherwise be dropped silently, and the
    response is the whole table group, so the caller sees its old value and no error."""
    mock_cls.get.return_value = _table_group()

    resp = _client().patch(f"/api/v1/table-groups/{TG_ID}", json={"description": "moved"})

    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch("testgen.api.deps.TableGroup")
def test_update_table_group_rejects_an_explicit_null(mock_cls, _perm):
    """Null reads as "clear it"; omitting the field is how you leave it alone."""
    mock_cls.get.return_value = _table_group()

    resp = _client().patch(f"/api/v1/table-groups/{TG_ID}", json={"schema_name": None})

    assert resp.status_code == 422
