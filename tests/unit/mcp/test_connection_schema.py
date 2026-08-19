"""Tests for the connection-parameter contract in ``mcp/tools/common.py``:
the per-flavor schema (``schema_for`` / ``resolve_mode``), label-keyed param
mapping (``apply_connection_params``), schema-driven validation
(``validate_connection_fields``), and mode inference (``infer_mode``).

The schema mirrors the per-flavor JS forms in
``ui/static/js/components/connection_form.js`` — these tests encode that contract.
"""

import pytest

from testgen.common.models.connection import Connection
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.tools.common import (
    ConnectionMode,
    Req,
    apply_connection_params,
    infer_mode,
    render_connection_body,
    resolve_mode,
    schema_for,
    validate_connection_fields,
)
from testgen.mcp.tools.markdown import MdDoc

pytestmark = pytest.mark.unit


def _conn(**overrides) -> Connection:
    """Build a Connection without touching the DB. Defaults to a complete PG config."""
    defaults = {
        "sql_flavor": "postgresql",
        "sql_flavor_code": "postgresql",
        "connection_name": "My DB",
        "project_host": "localhost",
        "project_port": "5432",
        "project_db": "testgen_local",
        "project_user": "testgen",
        "project_pw_encrypted": "pw",
        "connect_by_url": False,
        "connect_by_key": False,
        "connect_with_identity": False,
        "connect_with_service_principal": False,
        "max_threads": 4,
        "max_query_chars": 20000,
    }
    defaults.update(overrides)
    return Connection(**defaults)


# ---------------------------------------------------------------------------
# schema_for
# ---------------------------------------------------------------------------


def test_schema_for_unknown_code_raises():
    with pytest.raises(KeyError):
        schema_for("not_a_flavor")


def test_schema_for_postgresql_single_mode_host_fields():
    schema = schema_for("postgresql")
    assert schema.label == "PostgreSQL"
    assert len(schema.modes) == 1
    mode = schema.modes[0]
    assert mode.mode is None
    labels = {f.label: f for f in mode.fields}
    assert set(labels) == {"Host", "Port", "Database", "Username", "Password"}
    assert labels["Host"].requirement is Req.REQUIRED_UNLESS_URL
    assert labels["Username"].requirement is Req.REQUIRED
    assert labels["Password"].requirement is Req.OPTIONAL
    assert labels["Password"].secret is True
    assert mode.supports_url is True
    assert schema.url_field is not None and schema.url_field.label == "URL"
    assert labels["Host"].column == "project_host"
    assert labels["Username"].column == "project_user"
    assert labels["Password"].column == "project_pw_encrypted"


def test_schema_for_oracle_uses_service_name_label():
    labels = {f.label: f for f in schema_for("oracle").modes[0].fields}
    assert "Service Name" in labels
    assert "Database" not in labels
    assert labels["Service Name"].column == "project_db"


def test_schema_for_sap_hana_uses_database_label():
    labels = {f.label for f in schema_for("sap_hana").modes[0].fields}
    assert "Database" in labels


def test_schema_for_snowflake_two_modes_with_warehouse():
    schema = schema_for("snowflake")
    modes = {m.mode: m for m in schema.modes}
    assert set(modes) == {ConnectionMode.KEY_PAIR, ConnectionMode.PASSWORD}
    key_labels = {f.label: f for f in modes[ConnectionMode.KEY_PAIR].fields}
    pw_labels = {f.label: f for f in modes[ConnectionMode.PASSWORD].fields}
    assert "Warehouse" in key_labels and key_labels["Warehouse"].requirement is Req.OPTIONAL
    assert key_labels["Username"].requirement is Req.REQUIRED
    assert key_labels["Private Key"].requirement is Req.REQUIRED
    assert key_labels["Private Key"].secret is True
    assert key_labels["Private Key Passphrase"].requirement is Req.OPTIONAL
    assert "Password" not in key_labels
    assert pw_labels["Password"].requirement is Req.REQUIRED
    assert "Private Key" not in pw_labels
    assert all(m.supports_url for m in schema.modes)


def test_schema_for_databricks_modes_and_url_support():
    schema = schema_for("databricks")
    modes = {m.mode: m for m in schema.modes}
    assert set(modes) == {ConnectionMode.ACCESS_TOKEN, ConnectionMode.SERVICE_PRINCIPAL}
    pat = modes[ConnectionMode.ACCESS_TOKEN]
    oauth = modes[ConnectionMode.SERVICE_PRINCIPAL]
    pat_labels = {f.label: f for f in pat.fields}
    oauth_labels = {f.label: f for f in oauth.fields}
    assert pat_labels["Catalog"].column == "project_db"
    assert pat_labels["Catalog"].requirement is Req.REQUIRED_UNLESS_URL
    assert pat_labels["HTTP Path"].requirement is Req.REQUIRED_UNLESS_URL
    assert pat_labels["Access Token"].column == "project_pw_encrypted"
    assert pat_labels["Access Token"].requirement is Req.REQUIRED
    assert "Username" not in pat_labels  # auto-set to 'token'
    assert pat.supports_url is True
    assert oauth_labels["Client ID"].column == "project_user"
    assert oauth_labels["Client Secret"].column == "project_pw_encrypted"
    assert oauth_labels["Host"].requirement is Req.REQUIRED
    assert oauth.supports_url is False


def test_schema_for_bigquery_single_field_no_url():
    schema = schema_for("bigquery")
    assert len(schema.modes) == 1
    labels = {f.label: f for f in schema.modes[0].fields}
    assert set(labels) == {"Service Account Key"}
    assert labels["Service Account Key"].column == "service_account_key"
    assert labels["Service Account Key"].secret is True
    assert schema.modes[0].supports_url is False
    assert schema.url_field is None


def test_schema_for_salesforce_two_modes_field_mapping():
    schema = schema_for("salesforce_data360")
    modes = {m.mode: m for m in schema.modes}
    assert set(modes) == {ConnectionMode.JWT_BEARER, ConnectionMode.CLIENT_CREDENTIALS}
    jwt = {f.label: f for f in modes[ConnectionMode.JWT_BEARER].fields}
    cc = {f.label: f for f in modes[ConnectionMode.CLIENT_CREDENTIALS].fields}
    assert jwt["Login URL"].column == "project_host"
    assert jwt["Consumer Key"].column == "project_user"
    assert jwt["Username"].column == "project_db"
    assert jwt["Private Key"].column == "private_key"
    assert "Consumer Secret" not in jwt
    assert cc["Consumer Secret"].column == "project_pw_encrypted"
    assert "Username" not in cc and "Private Key" not in cc
    assert all(not m.supports_url for m in schema.modes)


# ---------------------------------------------------------------------------
# resolve_mode
# ---------------------------------------------------------------------------


def test_resolve_mode_single_mode_no_label():
    assert resolve_mode("postgresql", None).mode is None


def test_resolve_mode_single_mode_rejects_label():
    with pytest.raises(MCPUserError):
        resolve_mode("postgresql", "Password")


def test_resolve_mode_multi_mode_requires_label():
    with pytest.raises(MCPUserError) as exc:
        resolve_mode("snowflake", None)
    assert "Key-Pair" in str(exc.value) and "Password" in str(exc.value)


def test_resolve_mode_multi_mode_invalid_label():
    with pytest.raises(MCPUserError) as exc:
        resolve_mode("snowflake", "Bogus")
    assert "Key-Pair" in str(exc.value)


def test_resolve_mode_multi_mode_valid_label():
    assert resolve_mode("snowflake", "Key-Pair").mode is ConnectionMode.KEY_PAIR


# ---------------------------------------------------------------------------
# apply_connection_params
# ---------------------------------------------------------------------------


def test_apply_params_postgresql_maps_labels_to_columns():
    conn = Connection(sql_flavor="postgresql", sql_flavor_code="postgresql")
    apply_connection_params(
        conn,
        "postgresql",
        None,
        {"Host": "h", "Port": 5432, "Database": "d", "Username": "u", "Password": "p"},
    )
    assert conn.project_host == "h"
    assert conn.project_port == "5432"  # cast to str
    assert conn.project_db == "d"
    assert conn.project_user == "u"
    assert conn.project_pw_encrypted == "p"
    assert conn.connect_by_url is False


def test_apply_params_url_sets_connect_by_url():
    conn = Connection(sql_flavor="postgresql", sql_flavor_code="postgresql")
    apply_connection_params(conn, "postgresql", None, {"URL": "host:5432/db", "Username": "u"})
    assert conn.connect_by_url is True
    assert conn.url == "host:5432/db"
    assert conn.project_user == "u"


def test_apply_params_url_conflicts_with_host_group():
    conn = Connection(sql_flavor="postgresql", sql_flavor_code="postgresql")
    with pytest.raises(MCPUserError):
        apply_connection_params(conn, "postgresql", None, {"URL": "x", "Host": "h"})


def test_apply_params_url_on_unsupported_flavor_rejected():
    conn = Connection(sql_flavor="bigquery", sql_flavor_code="bigquery")
    with pytest.raises(MCPUserError):
        apply_connection_params(conn, "bigquery", None, {"URL": "x"})


def test_apply_params_unknown_key_rejected():
    conn = Connection(sql_flavor="postgresql", sql_flavor_code="postgresql")
    with pytest.raises(MCPUserError) as exc:
        apply_connection_params(conn, "postgresql", None, {"Hostname": "h"})
    assert "Hostname" in str(exc.value)


def test_apply_params_snowflake_key_pair_sets_flag():
    conn = Connection(sql_flavor="snowflake", sql_flavor_code="snowflake")
    apply_connection_params(
        conn,
        "snowflake",
        "Key-Pair",
        {"Host": "h", "Port": 443, "Database": "d", "Username": "u", "Private Key": "KEY"},
    )
    assert conn.connect_by_key is True
    assert conn.private_key == "KEY"


def test_apply_params_databricks_pat_auto_token_username():
    conn = Connection(sql_flavor="databricks", sql_flavor_code="databricks")
    apply_connection_params(
        conn,
        "databricks",
        "Access Token",
        {"Host": "h", "Port": 443, "Catalog": "main", "HTTP Path": "/sql/1.0/abc", "Access Token": "tok"},
    )
    assert conn.project_user == "token"
    assert conn.connect_by_key is False
    assert conn.project_db == "main"
    assert conn.http_path == "/sql/1.0/abc"
    assert conn.project_pw_encrypted == "tok"


def test_apply_params_databricks_oauth_client_id_secret():
    conn = Connection(sql_flavor="databricks", sql_flavor_code="databricks")
    apply_connection_params(
        conn,
        "databricks",
        "Service Principal (OAuth)",
        {"Host": "h", "Port": 443, "Catalog": "main", "HTTP Path": "/p", "Client ID": "cid", "Client Secret": "csec"},
    )
    assert conn.connect_by_key is True
    assert conn.project_user == "cid"
    assert conn.project_pw_encrypted == "csec"


def test_apply_params_databricks_oauth_rejects_url():
    conn = Connection(sql_flavor="databricks", sql_flavor_code="databricks")
    with pytest.raises(MCPUserError):
        apply_connection_params(conn, "databricks", "Service Principal (OAuth)", {"URL": "x"})


def test_apply_params_azure_managed_identity_sets_flag():
    conn = Connection(sql_flavor="mssql", sql_flavor_code="azure_mssql")
    apply_connection_params(conn, "azure_mssql", "Managed Identity", {"Host": "h", "Port": 1433, "Database": "d"})
    assert conn.connect_with_identity is True


def test_schema_for_azure_mssql_includes_service_principal():
    schema = schema_for("azure_mssql")
    modes = {m.mode for m in schema.modes}
    assert ConnectionMode.SERVICE_PRINCIPAL in modes
    spn = next(m for m in schema.modes if m.mode == ConnectionMode.SERVICE_PRINCIPAL)
    labels = {f.label for f in spn.fields}
    assert labels == {"Host", "Port", "Database", "Client ID", "Tenant ID", "Client Secret"}
    assert spn.supports_url is False
    assert spn.sets == {"connect_with_identity": False, "connect_with_service_principal": True}


def test_schema_for_synapse_mssql_includes_service_principal():
    """Synapse offers the full Azure schema — same ODBC ``Authentication=ActiveDirectoryServicePrincipal`` path."""
    modes = {m.mode for m in schema_for("synapse_mssql").modes}
    assert modes == {ConnectionMode.PASSWORD, ConnectionMode.MANAGED_IDENTITY, ConnectionMode.SERVICE_PRINCIPAL}
    spn = next(m for m in schema_for("synapse_mssql").modes if m.mode == ConnectionMode.SERVICE_PRINCIPAL)
    labels = {f.label for f in spn.fields}
    assert labels == {"Host", "Port", "Database", "Client ID", "Tenant ID", "Client Secret"}
    assert spn.sets == {"connect_with_identity": False, "connect_with_service_principal": True}


def test_schema_for_onelake_mssql_offers_entra_modes_only():
    """OneLake (Fabric SQL analytics endpoint) rejects SQL logins — schema exposes MI + SPN only."""
    schema = schema_for("onelake_mssql")
    modes = {m.mode for m in schema.modes}
    assert modes == {ConnectionMode.MANAGED_IDENTITY, ConnectionMode.SERVICE_PRINCIPAL}
    # URL-mode connect skips the Authentication= driver keyword; disallowed on this flavor.
    assert schema.url_field is None
    for mode in schema.modes:
        assert mode.supports_url is False


def test_schema_for_onelake_mssql_spn_fields():
    schema = schema_for("onelake_mssql")
    spn = next(m for m in schema.modes if m.mode == ConnectionMode.SERVICE_PRINCIPAL)
    labels = {f.label for f in spn.fields}
    assert labels == {"Host", "Port", "Database", "Client ID", "Tenant ID", "Client Secret"}
    assert spn.sets == {"connect_with_identity": False, "connect_with_service_principal": True}


def test_apply_params_onelake_service_principal_sets_flag():
    conn = Connection(sql_flavor="mssql", sql_flavor_code="onelake_mssql")
    apply_connection_params(
        conn,
        "onelake_mssql",
        "Service Principal (OAuth)",
        {"Host": "h", "Port": 1433, "Database": "d", "Client ID": "cid", "Tenant ID": "tid", "Client Secret": "csec"},
    )
    assert conn.connect_with_service_principal is True
    assert conn.connect_with_identity is False
    assert conn.project_user == "cid@tid"
    assert conn.project_pw_encrypted == "csec"


def test_apply_params_onelake_managed_identity_sets_flag():
    conn = Connection(sql_flavor="mssql", sql_flavor_code="onelake_mssql")
    apply_connection_params(conn, "onelake_mssql", "Managed Identity", {"Host": "h", "Port": 1433, "Database": "d"})
    assert conn.connect_with_identity is True
    assert conn.connect_with_service_principal is False


@pytest.mark.parametrize("flavor_code", ["azure_mssql", "synapse_mssql", "onelake_mssql"])
def test_render_connection_body_splits_spn_identity(flavor_code):
    """SPN connections store ``<cid>@<tid>`` in project_user; the display must
    split it back so Client ID and Tenant ID render as separate fields, not the
    raw concatenated string in both."""
    conn = _conn(
        sql_flavor_code=flavor_code,
        sql_flavor="mssql",
        connect_with_service_principal=True,
        project_host="h.example",
        project_port="1433",
        project_db="db",
        project_user="the-client-id@the-tenant-id",
    )
    doc = MdDoc()
    render_connection_body(doc, conn)
    body = doc.render()

    assert "**Client ID:** `the-client-id`" in body
    assert "**Tenant ID:** `the-tenant-id`" in body
    assert "the-client-id@the-tenant-id" not in body


def test_apply_params_azure_service_principal_sets_flag():
    conn = Connection(sql_flavor="mssql", sql_flavor_code="azure_mssql")
    apply_connection_params(
        conn,
        "azure_mssql",
        "Service Principal (OAuth)",
        {"Host": "h", "Port": 1433, "Database": "d", "Client ID": "cid", "Tenant ID": "tid", "Client Secret": "csec"},
    )
    assert conn.connect_with_service_principal is True
    assert conn.connect_with_identity is False
    assert conn.project_user == "cid@tid"
    assert conn.project_pw_encrypted == "csec"


def test_apply_params_synapse_service_principal_sets_flag():
    conn = Connection(sql_flavor="mssql", sql_flavor_code="synapse_mssql")
    apply_connection_params(
        conn,
        "synapse_mssql",
        "Service Principal (OAuth)",
        {"Host": "h", "Port": 1433, "Database": "d", "Client ID": "cid", "Tenant ID": "tid", "Client Secret": "csec"},
    )
    assert conn.connect_with_service_principal is True
    assert conn.connect_with_identity is False
    assert conn.project_user == "cid@tid"
    assert conn.project_pw_encrypted == "csec"


def test_apply_params_azure_service_principal_rejects_partial_identity():
    """Client ID without Tenant ID (or vice versa) yields a partial project_user
    that would silently fail at connect time — reject explicitly."""
    conn = Connection(sql_flavor="mssql", sql_flavor_code="azure_mssql")
    with pytest.raises(MCPUserError, match="both `Client ID` and `Tenant ID`"):
        apply_connection_params(
            conn,
            "azure_mssql",
            "Service Principal (OAuth)",
            {"Host": "h", "Port": 1433, "Database": "d", "Client ID": "cid", "Client Secret": "csec"},
        )
    with pytest.raises(MCPUserError, match="both `Client ID` and `Tenant ID`"):
        apply_connection_params(
            conn,
            "azure_mssql",
            "Service Principal (OAuth)",
            {"Host": "h", "Port": 1433, "Database": "d", "Tenant ID": "tid", "Client Secret": "csec"},
        )


def test_apply_params_salesforce_jwt_field_mapping():
    conn = Connection(sql_flavor="salesforce_data360", sql_flavor_code="salesforce_data360")
    apply_connection_params(
        conn,
        "salesforce_data360",
        "JWT Bearer Flow",
        {"Login URL": "https://my.salesforce.com", "Consumer Key": "ck", "Username": "u@x.com", "Private Key": "PK"},
    )
    assert conn.project_host == "https://my.salesforce.com"
    assert conn.project_user == "ck"
    assert conn.project_db == "u@x.com"
    assert conn.private_key == "PK"
    assert conn.connect_by_key is True


# ---------------------------------------------------------------------------
# validate_connection_fields — happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flavor_code", ["postgresql", "redshift", "redshift_spectrum", "mssql", "oracle", "sap_hana"])
def test_validate_passes_basic_host_auth_flavors(flavor_code):
    conn = _conn(sql_flavor_code=flavor_code, sql_flavor=flavor_code)
    assert validate_connection_fields(conn) == []


def test_validate_passes_azure_mssql_with_user_password():
    assert validate_connection_fields(_conn(sql_flavor_code="azure_mssql", sql_flavor="mssql")) == []


def test_validate_passes_azure_mssql_with_identity():
    conn = _conn(
        sql_flavor_code="azure_mssql",
        sql_flavor="mssql",
        connect_with_identity=True,
        project_user=None,
        project_pw_encrypted=None,
    )
    assert validate_connection_fields(conn) == []


def test_validate_passes_azure_mssql_with_service_principal():
    conn = _conn(
        sql_flavor_code="azure_mssql",
        sql_flavor="mssql",
        connect_with_service_principal=True,
        project_user="cid@tid",
        project_pw_encrypted="csec",
    )
    assert validate_connection_fields(conn) == []


def test_validate_passes_snowflake_password_auth():
    conn = _conn(sql_flavor_code="snowflake", sql_flavor="snowflake", project_port="443", connect_by_key=False)
    assert validate_connection_fields(conn) == []


def test_validate_passes_snowflake_key_pair_auth():
    conn = _conn(
        sql_flavor_code="snowflake",
        sql_flavor="snowflake",
        project_port="443",
        project_pw_encrypted=None,
        connect_by_key=True,
        private_key="-----BEGIN PRIVATE KEY-----\n...",
    )
    assert validate_connection_fields(conn) == []


def test_validate_passes_databricks_pat():
    conn = _conn(
        sql_flavor_code="databricks",
        sql_flavor="databricks",
        project_port="443",
        project_db="main",
        project_user="token",
        http_path="/sql/1.0/warehouses/abc",
    )
    assert validate_connection_fields(conn) == []


def test_validate_passes_bigquery():
    conn = _conn(
        sql_flavor_code="bigquery",
        sql_flavor="bigquery",
        project_host=None,
        project_port=None,
        project_db=None,
        project_user=None,
        project_pw_encrypted=None,
        service_account_key={"type": "service_account", "project_id": "demo"},
    )
    assert validate_connection_fields(conn) == []


def test_validate_passes_salesforce_jwt():
    conn = _conn(
        sql_flavor_code="salesforce_data360",
        sql_flavor="salesforce_data360",
        project_host="https://my.salesforce.com",
        project_port=None,
        project_db="user@x.com",
        project_user="consumer_key",
        project_pw_encrypted=None,
        connect_by_key=True,
        private_key="-----BEGIN PRIVATE KEY-----\n...",
    )
    assert validate_connection_fields(conn) == []


def test_validate_passes_salesforce_client_credentials():
    conn = _conn(
        sql_flavor_code="salesforce_data360",
        sql_flavor="salesforce_data360",
        project_host="https://my.salesforce.com",
        project_port=None,
        project_db=None,
        project_user="consumer_key",
        project_pw_encrypted="consumer_secret",
        connect_by_key=False,
        private_key=None,
    )
    assert validate_connection_fields(conn) == []


def test_validate_passes_connect_by_url_keeps_username():
    """URL mode: host/port/db not required, but Username STILL required (matches UI)."""
    conn = _conn(connect_by_url=True, url="localhost:5432/mydb", project_host=None, project_port=None, project_db=None)
    assert validate_connection_fields(conn) == []


# ---------------------------------------------------------------------------
# validate_connection_fields — divergence fix + per-flavor errors
# ---------------------------------------------------------------------------


def test_validate_url_mode_missing_username_fails():
    """The PR-flagged divergence: URL mode must still require Username."""
    conn = _conn(
        connect_by_url=True,
        url="localhost:5432/mydb",
        project_host=None,
        project_port=None,
        project_db=None,
        project_user=None,
    )
    assert "`Username` is required for PostgreSQL." in validate_connection_fields(conn)


@pytest.mark.parametrize(
    "label,model_attr",
    [("Host", "project_host"), ("Port", "project_port"), ("Database", "project_db"), ("Username", "project_user")],
)
def test_validate_postgresql_missing_field(label, model_attr):
    conn = _conn(**{model_attr: None})
    assert f"`{label}` is required for PostgreSQL." in validate_connection_fields(conn)


def test_validate_oracle_missing_service_name():
    conn = _conn(sql_flavor_code="oracle", sql_flavor="oracle", project_db=None)
    assert "`Service Name` is required for Oracle." in validate_connection_fields(conn)


def test_validate_postgresql_missing_url_when_connect_by_url():
    conn = _conn(connect_by_url=True, url=None, project_host=None, project_port=None)
    assert "`URL` is required for PostgreSQL." in validate_connection_fields(conn)


def test_validate_snowflake_missing_password_when_not_connect_by_key():
    conn = _conn(
        sql_flavor_code="snowflake",
        sql_flavor="snowflake",
        project_port="443",
        connect_by_key=False,
        project_pw_encrypted=None,
    )
    assert "`Password` is required for Snowflake." in validate_connection_fields(conn)


def test_validate_snowflake_missing_private_key_when_connect_by_key():
    conn = _conn(
        sql_flavor_code="snowflake",
        sql_flavor="snowflake",
        project_port="443",
        project_pw_encrypted=None,
        connect_by_key=True,
        private_key=None,
    )
    assert "`Private Key` is required for Snowflake." in validate_connection_fields(conn)


def test_validate_databricks_pat_missing_catalog():
    conn = _conn(
        sql_flavor_code="databricks",
        sql_flavor="databricks",
        project_port="443",
        project_user="token",
        project_db=None,
        http_path="/sql/1.0/warehouses/abc",
    )
    assert "`Catalog` is required for Databricks." in validate_connection_fields(conn)


def test_validate_databricks_pat_missing_http_path():
    conn = _conn(
        sql_flavor_code="databricks",
        sql_flavor="databricks",
        project_port="443",
        project_user="token",
        project_db="main",
        http_path=None,
    )
    assert "`HTTP Path` is required for Databricks." in validate_connection_fields(conn)


def test_validate_databricks_pat_missing_access_token():
    conn = _conn(
        sql_flavor_code="databricks",
        sql_flavor="databricks",
        project_port="443",
        project_user="token",
        project_db="main",
        http_path="/p",
        project_pw_encrypted=None,
    )
    assert "`Access Token` is required for Databricks." in validate_connection_fields(conn)


def test_validate_databricks_oauth_missing_client_id():
    conn = _conn(
        sql_flavor_code="databricks",
        sql_flavor="databricks",
        project_port="443",
        project_db="main",
        http_path="/p",
        connect_by_key=True,
        project_user=None,
        project_pw_encrypted="secret",
    )
    assert "`Client ID` is required for Databricks." in validate_connection_fields(conn)


def test_validate_bigquery_missing_service_account_key():
    conn = _conn(
        sql_flavor_code="bigquery",
        sql_flavor="bigquery",
        project_host=None,
        project_port=None,
        project_db=None,
        project_user=None,
        project_pw_encrypted=None,
        service_account_key=None,
    )
    assert "`Service Account Key` is required for Google BigQuery." in validate_connection_fields(conn)


def test_validate_salesforce_jwt_missing_private_key():
    conn = _conn(
        sql_flavor_code="salesforce_data360",
        sql_flavor="salesforce_data360",
        project_host="https://my.salesforce.com",
        project_port=None,
        project_db="user@x.com",
        project_user="ck",
        project_pw_encrypted=None,
        connect_by_key=True,
        private_key=None,
    )
    assert "`Private Key` is required for Salesforce Data 360." in validate_connection_fields(conn)


def test_validate_salesforce_jwt_missing_login_url():
    conn = _conn(
        sql_flavor_code="salesforce_data360",
        sql_flavor="salesforce_data360",
        project_host=None,
        project_port=None,
        project_db="user@x.com",
        project_user="ck",
        project_pw_encrypted=None,
        connect_by_key=True,
        private_key="key",
    )
    assert "`Login URL` is required for Salesforce Data 360." in validate_connection_fields(conn)


def test_validate_salesforce_client_credentials_missing_secret():
    conn = _conn(
        sql_flavor_code="salesforce_data360",
        sql_flavor="salesforce_data360",
        project_host="https://my.salesforce.com",
        project_port=None,
        project_db=None,
        project_user="ck",
        project_pw_encrypted=None,
        connect_by_key=False,
        private_key=None,
    )
    assert "`Consumer Secret` is required for Salesforce Data 360." in validate_connection_fields(conn)


def test_validate_azure_mssql_password_auth_missing_user():
    conn = _conn(sql_flavor_code="azure_mssql", sql_flavor="mssql", connect_with_identity=False, project_user=None)
    assert "`Username` is required for Azure SQL Database." in validate_connection_fields(conn)


# ---------------------------------------------------------------------------
# validate_connection_fields — name / threads / query-chars
# ---------------------------------------------------------------------------


def test_validate_missing_connection_name():
    assert "`connection_name` is required." in validate_connection_fields(_conn(connection_name=None))


def test_validate_connection_name_too_short():
    assert "`connection_name` must be between 3 and 40 characters." in validate_connection_fields(_conn(connection_name="ab"))


def test_validate_connection_name_too_long():
    assert "`connection_name` must be between 3 and 40 characters." in validate_connection_fields(_conn(connection_name="a" * 41))


@pytest.mark.parametrize("bad", [0, -1, 9, 100])
def test_validate_max_threads_out_of_range(bad):
    assert "`max_threads` must be between 1 and 8." in validate_connection_fields(_conn(max_threads=bad))


@pytest.mark.parametrize("bad", [499, 0, 50001, 100000])
def test_validate_max_query_chars_out_of_range(bad):
    assert "`max_query_chars` must be between 500 and 50000." in validate_connection_fields(_conn(max_query_chars=bad))


def test_validate_aggregates_all_errors():
    conn = _conn(connection_name="", project_host=None, project_port=None, max_threads=99)
    joined = "\n".join(validate_connection_fields(conn))
    assert "`connection_name` is required." in joined
    assert "`Host` is required for PostgreSQL." in joined
    assert "`Port` is required for PostgreSQL." in joined
    assert "`max_threads` must be between 1 and 8." in joined


# ---------------------------------------------------------------------------
# infer_mode
# ---------------------------------------------------------------------------


def test_infer_mode_single_mode_flavor_is_none():
    assert infer_mode(_conn(sql_flavor_code="postgresql")) is None


def test_infer_mode_snowflake_key_pair():
    assert infer_mode(_conn(sql_flavor_code="snowflake", sql_flavor="snowflake", connect_by_key=True)) is ConnectionMode.KEY_PAIR


def test_infer_mode_snowflake_password():
    assert infer_mode(_conn(sql_flavor_code="snowflake", sql_flavor="snowflake", connect_by_key=False)) is ConnectionMode.PASSWORD


def test_infer_mode_azure_identity():
    conn = _conn(sql_flavor_code="azure_mssql", sql_flavor="mssql", connect_with_identity=True)
    assert infer_mode(conn) is ConnectionMode.MANAGED_IDENTITY


def test_infer_mode_azure_service_principal():
    conn = _conn(
        sql_flavor_code="azure_mssql",
        sql_flavor="mssql",
        connect_with_service_principal=True,
    )
    assert infer_mode(conn) is ConnectionMode.SERVICE_PRINCIPAL


def test_infer_mode_synapse_service_principal():
    conn = _conn(
        sql_flavor_code="synapse_mssql",
        sql_flavor="mssql",
        connect_with_service_principal=True,
    )
    assert infer_mode(conn) is ConnectionMode.SERVICE_PRINCIPAL


def test_infer_mode_onelake_identity():
    conn = _conn(sql_flavor_code="onelake_mssql", sql_flavor="mssql", connect_with_identity=True)
    assert infer_mode(conn) is ConnectionMode.MANAGED_IDENTITY


def test_infer_mode_onelake_service_principal():
    conn = _conn(
        sql_flavor_code="onelake_mssql",
        sql_flavor="mssql",
        connect_with_service_principal=True,
    )
    assert infer_mode(conn) is ConnectionMode.SERVICE_PRINCIPAL


def test_infer_mode_onelake_defaults_to_service_principal():
    """No Entra flag set: OneLake defaults to SPN (external-client is the common case)."""
    conn = _conn(sql_flavor_code="onelake_mssql", sql_flavor="mssql")
    assert infer_mode(conn) is ConnectionMode.SERVICE_PRINCIPAL


def test_infer_mode_databricks_oauth():
    conn = _conn(sql_flavor_code="databricks", sql_flavor="databricks", connect_by_key=True)
    assert infer_mode(conn) is ConnectionMode.SERVICE_PRINCIPAL


def test_infer_mode_databricks_pat():
    conn = _conn(sql_flavor_code="databricks", sql_flavor="databricks", connect_by_key=False)
    assert infer_mode(conn) is ConnectionMode.ACCESS_TOKEN


def test_infer_mode_salesforce_jwt():
    conn = _conn(sql_flavor_code="salesforce_data360", sql_flavor="salesforce_data360", connect_by_key=True)
    assert infer_mode(conn) is ConnectionMode.JWT_BEARER
