"""Unit tests for Salesforce Data 360 flavor support."""

from unittest.mock import MagicMock, patch

import pytest

from testgen.common.database.flavor.flavor_service import ResolvedConnectionParams, resolve_connection_params
from testgen.common.database.flavor.salesforce_data360_flavor_service import (
    _TYPE_MAP,
    SalesforceData360FlavorService,
)


@pytest.fixture
def flavor_service():
    return SalesforceData360FlavorService()


@pytest.fixture
def client_credentials_params():
    return ResolvedConnectionParams(
        host="https://myorg.my.salesforce.com",
        username="consumer_key_123",
        password="consumer_secret_456",  # noqa: S106
        dbname="",
        connect_by_key=False,
        sql_flavor="salesforce_data360",
    )


@pytest.fixture
def jwt_bearer_params():
    return ResolvedConnectionParams(
        host="https://myorg.my.salesforce.com",
        username="consumer_key_123",
        dbname="admin@myorg.com",
        connect_by_key=True,
        private_key="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        sql_flavor="salesforce_data360",
    )


# --- FlavorService class properties ---

def test_flavor_service_properties(flavor_service):
    assert flavor_service.concat_operator == "||"
    assert flavor_service.quote_character == '"'
    assert flavor_service.varchar_type == "VARCHAR(1000)"
    assert flavor_service.default_uppercase is False
    assert flavor_service.test_query == "SELECT 1"
    assert flavor_service.qualifies_table_refs_with_schema is False
    assert flavor_service.metadata_via_api is True
    assert flavor_service.row_limiting_clause == "limit"


def test_get_table_ref_omits_schema(flavor_service):
    assert flavor_service.get_table_ref("data_space", "Account__dll") == '"Account__dll"'


# --- Connection string ---

def test_connection_string_is_dummy(flavor_service, client_credentials_params):
    assert flavor_service.get_connection_string(client_credentials_params) == "salesforce_data360://"


def test_connection_string_from_fields(flavor_service, client_credentials_params):
    assert flavor_service.get_connection_string_from_fields(client_credentials_params) == "salesforce_data360://"


# --- Connect args: Client Credentials flow ---

def test_connect_args_client_credentials(flavor_service, client_credentials_params):
    args = flavor_service.get_connect_args(client_credentials_params)
    assert args["login_url"] == "https://myorg.my.salesforce.com"
    assert args["client_id"] == "consumer_key_123"
    assert args["client_secret"] == "consumer_secret_456"  # noqa: S105
    assert "username" not in args
    assert "private_key" not in args
    assert "dataspace" not in args  # connection-only contexts (Test Connection)


# --- Connect args: JWT Bearer flow ---

def test_connect_args_jwt_bearer(flavor_service, jwt_bearer_params):
    args = flavor_service.get_connect_args(jwt_bearer_params)
    assert args["login_url"] == "https://myorg.my.salesforce.com"
    assert args["client_id"] == "consumer_key_123"
    assert args["username"] == "admin@myorg.com"
    assert args["private_key"].startswith("-----BEGIN RSA PRIVATE KEY-----")
    assert "client_secret" not in args
    assert "dataspace" not in args  # connection-only contexts (Test Connection)


# --- Connect args: Data Space pass-through ---

def test_connect_args_passes_dataspace_when_table_group_schema_set(flavor_service):
    params = ResolvedConnectionParams(
        host="https://myorg.my.salesforce.com",
        username="consumer_key_123",
        password="consumer_secret_456",  # noqa: S106
        dbname="",
        dbschema="marketing",
        connect_by_key=False,
        sql_flavor="salesforce_data360",
    )
    args = flavor_service.get_connect_args(params)
    assert args["dataspace"] == "marketing"


def test_connect_args_omits_dataspace_when_table_group_schema_empty(flavor_service):
    params = ResolvedConnectionParams(
        host="https://myorg.my.salesforce.com",
        username="consumer_key_123",
        dbname="admin@myorg.com",
        dbschema="",
        connect_by_key=True,
        private_key="-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----",
        sql_flavor="salesforce_data360",
    )
    args = flavor_service.get_connect_args(params)
    assert "dataspace" not in args


# --- Engine args ---

def test_engine_args(flavor_service, client_credentials_params):
    args = flavor_service.get_engine_args(client_credentials_params)
    assert args["pool_pre_ping"] is False
    assert "poolclass" in args


# --- Pre-connection queries ---

def test_no_pre_connection_queries(flavor_service, client_credentials_params):
    assert flavor_service.get_pre_connection_queries(client_credentials_params) == []


# --- Table reference (no schema prefix) ---

def test_get_table_ref_no_schema(flavor_service):
    ref = flavor_service.get_table_ref("default", "ssot__Account__dlm")
    assert ref == '"ssot__Account__dlm"'
    assert "default" not in ref


# --- resolve_connection_params mapping ---

def test_resolve_connection_params_mapping():
    # Use plain strings (not bytes) to avoid triggering the DecryptText path
    params = resolve_connection_params({
        "sql_flavor": "salesforce_data360",
        "project_host": "https://myorg.my.salesforce.com",
        "project_user": "consumer_key",
        "project_pw_encrypted": "plain_secret",
        "project_db": "admin@org.com",
        "connect_by_key": True,
        "private_key": "plain_key",
    })
    assert params.host == "https://myorg.my.salesforce.com"
    assert params.username == "consumer_key"
    assert params.password == "plain_secret"  # noqa: S105
    assert params.dbname == "admin@org.com"
    assert params.connect_by_key is True
    assert params.private_key == "plain_key"


# --- Schema metadata (get_schema_columns) ---

def test_get_schema_columns_returns_columns(flavor_service, client_credentials_params):
    mock_field = MagicMock()
    mock_field.name = "ssot__Name__c"
    mock_field.type = "STRING"

    mock_table = MagicMock()
    mock_table.name = "ssot__Account__dlm"
    mock_table.fields = [mock_field]

    mock_conn = MagicMock()
    mock_conn.list_tables.return_value = [mock_table]

    with patch(
        "salesforcecdpconnector.connection.SalesforceCDPConnection",
        return_value=mock_conn,
    ):
        columns = flavor_service.get_schema_columns(client_credentials_params, "default")

    assert columns is not None
    assert len(columns) == 1
    assert columns[0].schema_name == "default"
    assert columns[0].table_name == "ssot__Account__dlm"
    assert columns[0].column_name == "ssot__Name__c"
    assert columns[0].column_type == "varchar"
    assert columns[0].general_type == "A"
    assert columns[0].db_data_type == "STRING"
    assert columns[0].ordinal_position == 1
    assert columns[0].is_decimal is False


def test_get_schema_columns_type_mapping(flavor_service, client_credentials_params):
    """Verify all metadata types map correctly."""
    type_cases = [
        ("STRING", "varchar", "A", False),
        ("NUMBER", "numeric", "N", True),
        ("BIGINT", "bigint", "N", False),
        ("BOOLEAN", "boolean", "B", False),
        ("DATE", "date", "D", False),
        ("DATE_TIME", "datetime", "D", False),
    ]

    for meta_type, expected_col_type, expected_gen_type, expected_decimal in type_cases:
        mock_field = MagicMock()
        mock_field.name = "test_col"
        mock_field.type = meta_type

        mock_table = MagicMock()
        mock_table.name = "test_table"
        mock_table.fields = [mock_field]

        mock_conn = MagicMock()
        mock_conn.list_tables.return_value = [mock_table]

        with patch(
            "salesforcecdpconnector.connection.SalesforceCDPConnection",
            return_value=mock_conn,
        ):
            columns = flavor_service.get_schema_columns(client_credentials_params, "default")

        assert columns[0].column_type == expected_col_type, f"Failed for {meta_type}"
        assert columns[0].general_type == expected_gen_type, f"Failed for {meta_type}"
        assert columns[0].is_decimal == expected_decimal, f"Failed for {meta_type}"


def test_get_schema_columns_unknown_type_defaults_to_X(flavor_service, client_credentials_params):
    mock_field = MagicMock()
    mock_field.name = "exotic_col"
    mock_field.type = "HYPERLOGLOG"

    mock_table = MagicMock()
    mock_table.name = "test_table"
    mock_table.fields = [mock_field]

    mock_conn = MagicMock()
    mock_conn.list_tables.return_value = [mock_table]

    with patch(
        "salesforcecdpconnector.connection.SalesforceCDPConnection",
        return_value=mock_conn,
    ):
        columns = flavor_service.get_schema_columns(client_credentials_params, "default")

    assert columns[0].general_type == "X"
    # Unknown metadata types are preserved as a lowercased column_type so that
    # downstream views still surface the raw SF type instead of coercing to varchar.
    assert columns[0].column_type == "hyperloglog"


def test_get_schema_columns_multiple_tables(flavor_service, client_credentials_params):
    tables = []
    for tname, field_count in [("ssot__Account__dlm", 3), ("ssot__Individual__dlm", 5)]:
        mock_table = MagicMock()
        mock_table.name = tname
        mock_table.fields = []
        for i in range(field_count):
            f = MagicMock()
            f.name = f"field_{i}"
            f.type = "STRING"
            mock_table.fields.append(f)
        tables.append(mock_table)

    mock_conn = MagicMock()
    mock_conn.list_tables.return_value = tables

    with patch(
        "salesforcecdpconnector.connection.SalesforceCDPConnection",
        return_value=mock_conn,
    ):
        columns = flavor_service.get_schema_columns(client_credentials_params, "default")

    assert len(columns) == 8
    account_cols = [c for c in columns if c.table_name == "ssot__Account__dlm"]
    assert len(account_cols) == 3
    individual_cols = [c for c in columns if c.table_name == "ssot__Individual__dlm"]
    assert len(individual_cols) == 5


# --- Dialect registration ---

def test_dialect_is_registered():
    from sqlalchemy.dialects import registry as sa_registry

    # The import of the flavor service module triggers registration
    assert "salesforce_data360" in sa_registry.impls


# --- Type map completeness ---

def test_type_map_covers_all_known_types():
    # Data 360's metadata API has a small fixed vocabulary verified against
    # profiled DMOs and DLOs. Any unknown type falls through to general_type "X".
    expected_types = {"STRING", "NUMBER", "BIGINT", "BOOLEAN", "DATE", "DATE_TIME"}
    assert set(_TYPE_MAP.keys()) == expected_types


# --- SQL template files exist ---

def test_template_files_exist():
    from pathlib import Path

    base = Path(__file__).parents[3] / "testgen" / "template" / "flavors" / "salesforce_data360"
    assert (base / "profiling" / "project_profiling_query.sql").exists()
    assert (base / "profiling" / "project_secondary_profiling_query.sql").exists()
    assert (base / "profiling" / "templated_functions.yaml").exists()


# --- Templated functions YAML ---

def test_templated_functions_yaml_parses():
    from pathlib import Path

    import yaml

    path = Path(__file__).parents[3] / "testgen" / "template" / "flavors" / "salesforce_data360" / "profiling" / "templated_functions.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)

    # Data 360 uses native DATEDIFF('unit', ...) directly in templates, so the
    # DATEDIFF_* macros are intentionally omitted (only IS_NUM / IS_DATE need wrappers).
    required_functions = ["IS_NUM", "IS_DATE"]
    for func_name in required_functions:
        assert func_name in data, f"Missing templated function: {func_name}"


def test_profiling_query_uses_data360_datediff_syntax():
    from pathlib import Path

    path = Path(__file__).parents[3] / "testgen" / "template" / "flavors" / "salesforce_data360" / "profiling" / "project_profiling_query.sql"
    sql = path.read_text()

    # Data 360 uses inline DATEDIFF('unit', start, end) — string units, not bare identifiers.
    assert "DATEDIFF('day'" in sql
    assert "DATEDIFF('week'" in sql
    assert "DATEDIFF('month'" in sql


def test_is_num_uses_regexp_like():
    from pathlib import Path

    import yaml

    path = Path(__file__).parents[3] / "testgen" / "template" / "flavors" / "salesforce_data360" / "profiling" / "templated_functions.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)

    assert "REGEXP_LIKE" in data["IS_NUM"]
    assert "~" not in data["IS_NUM"]  # No PG regex operator


def test_is_date_uses_regexp_like():
    from pathlib import Path

    import yaml

    path = Path(__file__).parents[3] / "testgen" / "template" / "flavors" / "salesforce_data360" / "profiling" / "templated_functions.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)

    assert "REGEXP_LIKE" in data["IS_DATE"]
    assert "~" not in data["IS_DATE"]
    assert "LEFT(" not in data["IS_DATE"]  # Should use SUBSTR, not LEFT
    assert "::" not in data["IS_DATE"]  # Should use CAST, not ::


# --- Profiling template syntax checks ---

def test_profiling_query_has_no_pg_specific_syntax():
    from pathlib import Path

    path = Path(__file__).parents[3] / "testgen" / "template" / "flavors" / "salesforce_data360" / "profiling" / "project_profiling_query.sql"
    content = path.read_text()

    assert "TABLESAMPLE" not in content
    assert "STRING_AGG" not in content
    assert "TRANSLATE(" not in content
    assert " ~ " not in content  # PG regex operator
    # Check for PG escape string syntax (E'...') — but not substrings like "CASE '"
    import re
    assert not re.search(r"\bE'", content), "Found PostgreSQL E-string escape syntax"
    assert "LEFT(" not in content
    assert "::FLOAT" not in content
    assert "::BIGINT" not in content
    assert "::NUMERIC" not in content


def test_profiling_query_uses_data360_alternatives():
    from pathlib import Path

    path = Path(__file__).parents[3] / "testgen" / "template" / "flavors" / "salesforce_data360" / "profiling" / "project_profiling_query.sql"
    content = path.read_text()

    assert "REGEXP_LIKE" in content
    assert "ARRAY_JOIN(ARRAY_AGG" in content
    assert "SUBSTR(" in content
    assert "ORDER BY RANDOM()" in content


def test_secondary_profiling_query_syntax():
    from pathlib import Path

    path = Path(__file__).parents[3] / "testgen" / "template" / "flavors" / "salesforce_data360" / "profiling" / "project_secondary_profiling_query.sql"
    content = path.read_text()

    assert "STRING_AGG" not in content
    assert "ARRAY_JOIN(ARRAY_AGG" in content
    assert "TABLESAMPLE" not in content
    assert '"{DATA_SCHEMA}".' not in content  # No schema prefix in FROM
