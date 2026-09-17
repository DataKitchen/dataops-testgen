"""Tests for testgen.api.connections — connection reads."""

import re
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from testgen.api.connections import get_connection, list_connections, router
from testgen.api.deps import db_session, get_authorized_user
from testgen.api.enums import AuthenticationMethod
from testgen.common.connection_schema import FLAVOR_CONNECTION_SCHEMA, SECRET_COLUMNS
from testgen.common.models.connection import Connection
from testgen.common.models.custom_types import EncryptedBytea, EncryptedJson

pytestmark = pytest.mark.unit

DEPS = "testgen.api.deps"
MODULE = "testgen.api.connections"


def _conn(**overrides):
    """A Connection-shaped stub. Every schema column defaults to empty so a test
    only sets what its flavor populates."""
    defaults = {
        "connection_id": 3,
        "connection_name": "Prod",
        "project_code": "demo",
        "sql_flavor_code": "postgresql",
        "project_host": None,
        "project_port": None,
        "project_db": None,
        "project_user": None,
        "project_pw_encrypted": None,
        "warehouse": None,
        "http_path": None,
        "private_key": None,
        "private_key_passphrase": None,
        "service_account_key": None,
        "url": None,
        "connect_by_url": False,
        "connect_by_key": False,
        "connect_with_identity": False,
        "connect_with_service_principal": False,
        "max_threads": 4,
        "max_query_chars": 20000,
    }
    return MagicMock(**{**defaults, **overrides})


def _row(**overrides):
    defaults = {
        "connection_id": 3,
        "connection_name": "Prod",
        "project_code": "demo",
        "sql_flavor_code": "snowflake",
        "table_group_count": 2,
    }
    return MagicMock(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# resolve_connection
# ---------------------------------------------------------------------------


def _resolve(connection, *, allowed=True):
    from testgen.api.deps import resolve_connection
    dep = resolve_connection("view").dependency
    with patch(f"{DEPS}.Connection") as mock_cls, \
         patch(f"{DEPS}.has_project_permission", return_value=allowed):
        mock_cls.get.return_value = connection
        return dep(connection_id=3, user=MagicMock())


def test_resolve_connection_returns_connection_when_permitted():
    connection = _conn()
    assert _resolve(connection) is connection


def test_resolve_connection_404_when_missing():
    with pytest.raises(HTTPException) as exc:
        _resolve(None)
    assert exc.value.status_code == 404


def test_resolve_connection_404_when_not_permitted():
    with pytest.raises(HTTPException) as exc:
        _resolve(_conn(), allowed=False)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.Connection")
def test_list_connections_maps_flavor_code_to_display_label(mock_cls):
    mock_cls.list_for_project.return_value = ([_row()], 1)

    result = list_connections(project_code="demo", page=1, limit=20)

    assert result.total == 1
    assert result.items[0].database_type == "Snowflake"
    assert result.items[0].table_group_count == 2


@patch(f"{MODULE}.Connection")
def test_list_connections_passes_pagination_through(mock_cls):
    mock_cls.list_for_project.return_value = ([], 0)

    result = list_connections(project_code="demo", page=3, limit=50)

    mock_cls.list_for_project.assert_called_once_with("demo", page=3, limit=50)
    assert (result.page, result.limit, result.total, result.items) == (3, 50, 0, [])


@patch(f"{MODULE}.Connection")
def test_list_connections_omits_connection_parameters(mock_cls):
    mock_cls.list_for_project.return_value = ([_row()], 1)

    item = list_connections(project_code="demo", page=1, limit=20).items[0]

    assert not {"settings", "host", "database"} & set(item.model_dump())


# ---------------------------------------------------------------------------
# detail — flavor-shaped settings
# ---------------------------------------------------------------------------


def test_get_connection_snowflake_key_pair():
    connection = _conn(
        sql_flavor_code="snowflake",
        connect_by_key=True,
        project_host="acme.snowflakecomputing.com",
        project_port="443",
        project_db="ANALYTICS",
        project_user="svc_testgen",
        warehouse="COMPUTE_WH",
        private_key="-----BEGIN PRIVATE KEY-----",
        private_key_passphrase="hunter2",  # noqa: S106 — fixture value, asserted as redacted
    )

    result = get_connection(connection)

    assert result.database_type == "Snowflake"
    assert result.authentication is AuthenticationMethod.key_pair
    assert result.settings == {
        "host": "acme.snowflakecomputing.com",
        "port": "443",
        "database": "ANALYTICS",
        "username": "svc_testgen",
        "warehouse": "COMPUTE_WH",
    }


def test_get_connection_salesforce_relabels_shared_columns():
    """project_host is the login URL and project_db the username on this flavor."""
    connection = _conn(
        sql_flavor_code="salesforce_data360",
        connect_by_key=True,
        project_host="https://acme.my.salesforce.com",
        project_user="3MVG9consumerkey",
        project_db="svc@acme.com",
        private_key="-----BEGIN PRIVATE KEY-----",
    )

    result = get_connection(connection)

    assert result.authentication is AuthenticationMethod.jwt_bearer
    assert result.settings == {
        "login_url": "https://acme.my.salesforce.com",
        "consumer_key": "3MVG9consumerkey",
        "username": "svc@acme.com",
    }


def test_get_connection_oracle_calls_project_db_the_service_name():
    connection = _conn(
        sql_flavor_code="oracle",
        project_host="db.acme.com",
        project_port="1521",
        project_db="ORCLPDB1",
        project_user="testgen",
        project_pw_encrypted="secret",
    )

    assert get_connection(connection).settings == {
        "host": "db.acme.com",
        "port": "1521",
        "service_name": "ORCLPDB1",
        "username": "testgen",
    }


def test_get_connection_databricks_calls_project_db_the_catalog():
    connection = _conn(
        sql_flavor_code="databricks",
        project_host="acme.cloud.databricks.com",
        project_port="443",
        http_path="/sql/1.0/warehouses/abc",
        project_db="main",
        project_user="token",
        project_pw_encrypted="dapi-secret",
    )

    result = get_connection(connection)

    assert result.authentication is AuthenticationMethod.access_token
    assert result.settings == {
        "host": "acme.cloud.databricks.com",
        "port": "443",
        "http_path": "/sql/1.0/warehouses/abc",
        "catalog": "main",
    }


def test_get_connection_bigquery_reports_service_account_auth():
    connection = _conn(
        sql_flavor_code="bigquery",
        project_db="acme-analytics",
        service_account_key={"project_id": "acme-analytics"},
    )

    result = get_connection(connection)

    assert result.authentication is AuthenticationMethod.service_account
    # BigQuery's only schema field is the Service Account Key, which is secret and
    # filtered out. Its Project ID (stored in project_db) is not in the field map, so
    # settings is empty by construction — not a bug, but not the full story either.
    assert result.settings == {}


def test_get_connection_splits_service_principal_identity():
    """The mssql family packs client and tenant id into one column."""
    connection = _conn(
        sql_flavor_code="azure_mssql",
        connect_with_service_principal=True,
        project_host="acme.database.windows.net",
        project_port="1433",
        project_db="sales",
        project_user="client-abc@tenant-xyz",
        project_pw_encrypted="secret",
    )

    result = get_connection(connection)

    assert result.authentication is AuthenticationMethod.service_principal
    assert result.settings["client_id"] == "client-abc"
    assert result.settings["tenant_id"] == "tenant-xyz"


def test_get_connection_url_mode_reports_the_url_and_its_parts():
    """``Connection.save()`` derives host, port and database from the URL and stores
    all of them, so a URL-mode connection reports the parts alongside the URL."""
    connection = _conn(
        sql_flavor_code="postgresql",
        connect_by_url=True,
        url="db.acme.com:5432/sales",
        project_host="db.acme.com",
        project_port="5432",
        project_db="sales",
        project_user="testgen",
        project_pw_encrypted="secret",
    )

    assert get_connection(connection).settings == {
        "host": "db.acme.com",
        "port": "5432",
        "database": "sales",
        "username": "testgen",
        "url": "db.acme.com:5432/sales",
    }


def test_get_connection_reports_thread_and_expression_limits():
    result = get_connection(_conn(max_threads=6, max_query_chars=30000))

    assert (result.max_threads, result.max_expression_length) == (6, 30000)


# ---------------------------------------------------------------------------
# the credential guarantee
# ---------------------------------------------------------------------------

_SECRET_VALUES = {
    "project_pw_encrypted": "PW-LEAK",
    "private_key": "KEY-LEAK",
    "private_key_passphrase": "PASS-LEAK",
    "service_account_key": {"private_key": "SA-LEAK"},
}


@pytest.mark.parametrize("flavor_code", sorted(FLAVOR_CONNECTION_SCHEMA))
def test_get_connection_never_returns_credentials(flavor_code):
    """Every flavor, every auth mode: no encrypted column reaches the response."""
    for connect_by_key in (False, True):
        for identity, spn in ((False, False), (True, False), (False, True)):
            connection = _conn(
                sql_flavor_code=flavor_code,
                connect_by_key=connect_by_key,
                connect_with_identity=identity,
                connect_with_service_principal=spn,
                project_host="host",
                project_port="1234",
                project_db="db",
                project_user="user@tenant",
                warehouse="wh",
                http_path="/path",
                url="host/db",
                **_SECRET_VALUES,
            )
            body = str(get_connection(connection).model_dump())
            assert "LEAK" not in body, f"{flavor_code} leaked a credential: {body}"


def test_every_encrypted_column_is_marked_secret():
    """The sweep above only proves anything while ``secret`` covers every encrypted
    column a field maps to. Derived from the ORM column types, so an encrypted column
    given a field without ``secret=True`` fails here rather than leaking through a
    green suite. An encrypted column no field maps is unreachable through
    ``connection_display_values``, which walks schema fields alone."""
    encrypted = {
        column.name
        for column in Connection.__table__.columns
        if isinstance(column.type, EncryptedBytea | EncryptedJson)
    }
    mapped = {
        fld.column
        for schema in FLAVOR_CONNECTION_SCHEMA.values()
        for mode in schema.modes
        for fld in mode.fields
    }

    assert encrypted & mapped == SECRET_COLUMNS


def test_no_field_maps_to_a_nonexistent_column():
    """Both suites build connections from MagicMock, which fabricates any attribute,
    so a typo in a ``column`` would silently drop the field from ``settings`` and make
    the flavor permanently fail validation on the write path."""
    for schema in FLAVOR_CONNECTION_SCHEMA.values():
        fields = [f for m in schema.modes for f in m.fields]
        if schema.url_field is not None:
            fields.append(schema.url_field)
        for fld in fields:
            # An in_parameters field names a key inside the ``parameters`` JSON rather
            # than a column of its own, so that column is what has to exist.
            attribute = "parameters" if fld.in_parameters else fld.column
            assert hasattr(Connection, attribute), f"{schema.code}: {fld.label} -> {attribute}"


def test_settings_keys_are_snake_case_tokens():
    """Every label a flavor can publish maps to a usable wire key."""
    from testgen.common.connection_schema import settings_key

    for schema in FLAVOR_CONNECTION_SCHEMA.values():
        fields = [f for m in schema.modes for f in m.fields if not f.secret]
        if schema.url_field is not None:
            fields.append(schema.url_field)
        for fld in fields:
            token = settings_key(fld.label)
            assert re.fullmatch(r"[a-z0-9]+(_[a-z0-9]+)*", token), f"{schema.code}: {fld.label} -> {token}"


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
@patch(f"{MODULE}.Connection")
def test_list_connections_route_is_reachable(mock_cls, _perm):
    mock_cls.list_for_project.return_value = ([_row()], 1)

    resp = _client().get("/api/v1/projects/DEFAULT/connections")

    assert resp.status_code == 200
    assert resp.json()["items"][0]["database_type"] == "Snowflake"


@pytest.mark.parametrize("query", ["?page=0", "?limit=0", "?limit=101"])
@patch("testgen.api.deps.has_project_permission", return_value=True)
@patch(f"{MODULE}.Connection")
def test_list_connections_rejects_out_of_range_pagination(mock_cls, _perm, query):
    mock_cls.list_for_project.return_value = ([], 0)

    resp = _client().get(f"/api/v1/projects/DEFAULT/connections{query}")

    assert resp.status_code == 422


@patch("testgen.api.deps.has_project_permission", return_value=False)
@patch(f"{MODULE}.Connection")
def test_list_connections_404_without_view_permission(mock_cls, _perm):
    """Pins the permission string the resolver is given, not just that one is given."""
    mock_cls.list_for_project.return_value = ([_row()], 1)

    assert _client().get("/api/v1/projects/DEFAULT/connections").status_code == 404


@patch("testgen.api.deps.has_project_permission")
@patch(f"{MODULE}.Connection")
def test_list_connections_asks_for_view_permission(mock_cls, mock_perm):
    mock_cls.list_for_project.return_value = ([], 0)
    mock_perm.return_value = True

    _client().get("/api/v1/projects/DEFAULT/connections")

    assert mock_perm.call_args.args[2] == "view"


@patch("testgen.api.deps.Connection")
@patch("testgen.api.deps.has_project_permission", return_value=False)
def test_get_connection_404_without_view_permission(_perm, mock_deps_cls):
    mock_deps_cls.get.return_value = _conn()

    assert _client().get("/api/v1/connections/3").status_code == 404


def test_get_connection_rejects_a_non_integer_id():
    assert _client().get("/api/v1/connections/not-an-int").status_code == 422
