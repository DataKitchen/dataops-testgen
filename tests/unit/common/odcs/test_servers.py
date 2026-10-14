import json
from importlib import resources
from unittest.mock import MagicMock

import pytest
import yaml

from testgen.common.flavors import SqlFlavorCode
from testgen.common.odcs.servers import (
    CUSTOM_FIELDS,
    FLAVOR_TO_SERVER_TYPE,
    ODCS_API_VERSION,
    ODCS_KIND,
    CustomServerReason,
    ServerType,
    build_server_block,
)
from testgen.common.odcs.validation import validate_document

pytestmark = pytest.mark.unit


def _connection(flavor, **attrs):
    connection = MagicMock()
    connection.sql_flavor_code = flavor
    connection.connection_name = "warehouse"
    for key, value in attrs.items():
        setattr(connection, key, value)
    return connection


def _validation_problems(entry):
    document = {
        "apiVersion": ODCS_API_VERSION,
        "kind": ODCS_KIND,
        "id": "orders",
        "version": "1.0.0",
        "status": "draft",
        "servers": [entry],
    }
    return validate_document(document)


def test_every_server_type_is_lower_case():
    for member in ServerType:
        assert member.value == member.value.lower()


def test_postgres_carries_host_port_database_and_schema():
    connection = _connection("postgresql", project_host="db.example", project_port="5432", project_db="sales")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public")).entry

    assert block["type"] == ServerType.POSTGRES
    assert block["host"] == "db.example"
    assert block["port"] == 5432
    assert block["database"] == "sales"
    assert block["schema"] == "public"
    assert block["server"]


def test_databricks_requires_catalog_and_schema():
    connection = _connection("databricks", project_db="main")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="bronze")).entry

    assert block["type"] == ServerType.DATABRICKS
    assert block["catalog"] == "main"
    assert block["schema"] == "bronze"


def test_a_missing_required_field_falls_back_to_a_custom_entry_rather_than_a_partial_typed_one():
    connection = _connection("postgresql", project_host=None, project_port="5432", project_db="sales")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert block.entry == {"server": "warehouse", "type": "custom", "port": 5432, "database": "sales", "schema": "public"}
    assert block.custom_reason == CustomServerReason(server_type=ServerType.POSTGRES, missing_fields=("host",))
    assert _validation_problems(block.entry) == []


def test_a_typed_entry_has_no_custom_reason():
    connection = _connection("postgresql", project_host="db.example", project_port="5432", project_db="sales")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert block.custom_reason is None


def test_oracle_requires_host_port_and_service_name():
    connection = _connection("oracle", project_host="ora.example", project_port="1521", project_db="ORCLPDB1")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="app")).entry

    assert block["type"] == ServerType.ORACLE
    assert block["host"] == "ora.example"
    assert block["port"] == 1521
    assert block["serviceName"] == "ORCLPDB1"


def test_hana_requires_only_host():
    connection = _connection("sap_hana", project_host="hana.example", project_port=None, project_db=None)
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="app")).entry

    assert block["type"] == ServerType.HANA
    assert block["host"] == "hana.example"
    assert "port" not in block
    assert "database" not in block


def test_hana_missing_host_falls_back_to_custom():
    connection = _connection("sap_hana", project_host=None, project_port="30015", project_db=None)
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="app"))

    assert block.entry == {"server": "warehouse", "type": "custom", "port": 30015, "schema": "app"}
    assert block.custom_reason == CustomServerReason(server_type=ServerType.HANA, missing_fields=("host",))


def test_bigquery_reads_the_project_id_from_the_service_account_key():
    connection = _connection(
        "bigquery", project_db=None, service_account_key={"project_id": "acme-warehouse"}
    )
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="analytics")).entry

    assert block["type"] == ServerType.BIGQUERY
    assert block["project"] == "acme-warehouse"
    assert block["dataset"] == "analytics"


def test_bigquery_without_a_service_account_key_falls_back_to_custom():
    # A connection on application default credentials works, but names its project nowhere TestGen reads.
    connection = _connection("bigquery", project_db=None, service_account_key=None)
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="analytics"))

    assert block.entry == {"server": "warehouse", "type": "custom", "dataset": "analytics"}
    assert block.custom_reason == CustomServerReason(server_type=ServerType.BIGQUERY, missing_fields=("project",))
    assert _validation_problems(block.entry) == []


def test_snowflake_carries_account_database_schema_and_optional_warehouse():
    connection = _connection(
        "snowflake", project_host="xy12345.snowflakecomputing.com", project_db="sales", warehouse="wh_main"
    )
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public")).entry

    assert block["type"] == ServerType.SNOWFLAKE
    assert block["account"] == "xy12345.snowflakecomputing.com"
    assert block["database"] == "sales"
    assert block["schema"] == "public"
    assert block["warehouse"] == "wh_main"


def test_snowflake_omits_warehouse_when_not_supplied():
    connection = _connection("snowflake", project_host="xy12345.snowflakecomputing.com", project_db="sales")
    connection.warehouse = None
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public")).entry

    assert "warehouse" not in block


def test_mssql_requires_host_database_and_schema():
    connection = _connection("mssql", project_host="db.example", project_port="1433", project_db="orders")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="dbo")).entry

    assert block["type"] == ServerType.SQLSERVER
    assert block["host"] == "db.example"
    assert block["database"] == "orders"
    assert block["schema"] == "dbo"


def test_azure_mssql_also_maps_to_sqlserver():
    connection = _connection("azure_mssql", project_host="db.example", project_port="1433", project_db="orders")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="dbo")).entry

    assert block["type"] == ServerType.SQLSERVER


def test_synapse_requires_host_port_and_database():
    connection = _connection("synapse_mssql", project_host="syn.example", project_port="1433", project_db="dw")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public")).entry

    assert block["type"] == ServerType.SYNAPSE
    assert block["host"] == "syn.example"
    assert block["port"] == 1433
    assert block["database"] == "dw"


def test_redshift_requires_database_and_schema():
    connection = _connection("redshift", project_host="rs.example", project_db="analytics")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public")).entry

    assert block["type"] == ServerType.REDSHIFT
    assert block["database"] == "analytics"
    assert block["schema"] == "public"
    assert block["host"] == "rs.example"


@pytest.mark.parametrize(("flavor", "attrs", "expected"), [
    (
        SqlFlavorCode.REDSHIFT_SPECTRUM,
        {"project_host": "rs.example", "project_port": "5439", "project_db": "analytics"},
        {"host": "rs.example", "port": 5439, "database": "analytics", "schema": "public"},
    ),
    (
        SqlFlavorCode.ONELAKE_MSSQL,
        {"project_host": "x.datawarehouse.fabric.microsoft.com", "project_port": "1433", "project_db": "lake"},
        {"host": "x.datawarehouse.fabric.microsoft.com", "port": 1433, "database": "lake", "schema": "public"},
    ),
    (
        SqlFlavorCode.SALESFORCE_DATA360,
        {"project_host": "https://acme.my.salesforce.com", "project_db": "user@example.com"},
        {"endpointUrl": "https://acme.my.salesforce.com"},
    ),
    (
        SqlFlavorCode.SALESFORCE_DATA360,
        {"project_host": "acme.my.salesforce.com", "project_db": "user@example.com"},
        {"host": "acme.my.salesforce.com"},
    ),
    (SqlFlavorCode.FILES, {"parameters": {"base_path": " /data/claims "}}, {"path": "/data/claims"}),
    (
        SqlFlavorCode.S3,
        {"parameters": {"base_uri": "s3://claims-bucket/incoming/", "region": "us-east-1"}},
        {"location": "s3://claims-bucket/incoming", "region": "us-east-1"},
    ),
    (
        SqlFlavorCode.S3,
        {"parameters": {"base_uri": "s3://claims-bucket/monthly reports/café/", "region": "us-east-1"}},
        {"location": "s3://claims-bucket/monthly%20reports/caf%C3%A9", "region": "us-east-1"},
    ),
    (
        SqlFlavorCode.S3,
        {"parameters": {"base_uri": "s3://claims-bucket/already%20encoded", "region": "us-east-1"}},
        {"location": "s3://claims-bucket/already%20encoded", "region": "us-east-1"},
    ),
    (
        SqlFlavorCode.SALESFORCE_DATA360,
        {"project_host": "https://acme.my.salesforce.com/login page", "project_db": "user@example.com"},
        {"endpointUrl": "https://acme.my.salesforce.com/login%20page"},
    ),
    (
        SqlFlavorCode.AZURE_BLOB,
        {"parameters": {"storage_account": "claimsacct", "container": "incoming"}},
        {"account": "claimsacct", "location": "az://incoming"},
    ),
])
def test_a_flavor_with_no_server_type_gets_a_valid_custom_entry(flavor, attrs, expected):
    defaults = {"project_host": None, "project_port": None, "project_db": None, "parameters": {}}
    connection = _connection(flavor, **{**defaults, **attrs})
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert block.entry == {"server": "warehouse", "type": "custom", **expected}
    assert block.custom_reason == CustomServerReason(server_type=None)
    assert _validation_problems(block.entry) == []


def test_every_flavor_is_either_mapped_or_given_custom_fields():
    # A flavor added without a decision here would raise a KeyError at contract creation.
    assert set(FLAVOR_TO_SERVER_TYPE) | set(CUSTOM_FIELDS) == set(SqlFlavorCode)


def test_no_flavor_is_both_mapped_and_given_custom_fields():
    assert not set(FLAVOR_TO_SERVER_TYPE) & set(CUSTOM_FIELDS)


def test_the_flavor_map_is_keyed_by_the_flavor_enum():
    assert all(isinstance(code, SqlFlavorCode) for code in FLAVOR_TO_SERVER_TYPE)


def test_duckdb_carries_its_database_file_as_the_database():
    connection = _connection(SqlFlavorCode.DUCKDB, parameters={"database_file": " /data/sales.duckdb "})
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="main")).entry

    assert block["type"] == ServerType.DUCKDB
    assert block["database"] == "/data/sales.duckdb"
    assert block["schema"] == "main"


def test_a_duckdb_entry_with_no_schema_is_typed_and_valid():
    connection = _connection(SqlFlavorCode.DUCKDB, parameters={"database_file": "/data/sales.duckdb"})
    block = build_server_block(connection, table_group=MagicMock(table_group_schema=None))

    assert block.entry == {"server": "warehouse", "type": "duckdb", "database": "/data/sales.duckdb"}
    assert block.custom_reason is None
    assert _validation_problems(block.entry) == []


def test_a_duckdb_connection_with_no_database_file_falls_back_to_custom():
    connection = _connection(SqlFlavorCode.DUCKDB, parameters={})
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="main"))

    assert block.entry == {"server": "warehouse", "type": "custom", "schema": "main"}
    assert block.custom_reason == CustomServerReason(server_type=ServerType.DUCKDB, missing_fields=("database",))


def test_the_server_types_value_is_a_plain_string_not_the_enum_member():
    # isinstance(block["type"], str) is not enough -- ServerType is a StrEnum, so a member
    # passes isinstance(x, str) and compares equal to its own value ("postgres" ==
    # ServerType.POSTGRES is True), which is exactly why every earlier test here asserting
    # `block["type"] == ServerType.POSTGRES` kept passing with the enum member still leaked
    # in. type(x) is str is the one check that tells the two apart, because it is also the
    # one check yaml.safe_dump's representer lookup actually uses.
    connection = _connection("postgresql", project_host="db.example", project_port="5432", project_db="sales")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public")).entry

    assert type(block["type"]) is str
    assert block["type"] == "postgres"


def test_a_server_block_survives_yaml_serialization():
    connection = _connection("postgresql", project_host="db.example", project_port="5432", project_db="sales")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public")).entry

    yaml.safe_dump(block)


def test_the_pinned_api_version_is_a_member_of_the_schemas_enum():
    schema = json.loads(
        resources.files("testgen.common.odcs.schemas").joinpath("odcs-json-schema-v3.2.0.json").read_text()
    )
    assert ODCS_API_VERSION in schema["properties"]["apiVersion"]["enum"]
