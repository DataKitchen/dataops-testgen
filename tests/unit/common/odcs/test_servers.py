import json
from importlib import resources
from unittest.mock import MagicMock

import pytest
import yaml

from testgen.common.flavors import SqlFlavorCode
from testgen.common.odcs.servers import (
    FLAVOR_TO_SERVER_TYPE,
    ODCS_API_VERSION,
    UNMAPPABLE_FLAVORS,
    ServerType,
    build_server_block,
)

pytestmark = pytest.mark.unit


def _connection(flavor, **attrs):
    connection = MagicMock()
    connection.sql_flavor_code = flavor
    connection.connection_name = "warehouse"
    for key, value in attrs.items():
        setattr(connection, key, value)
    return connection


def test_every_server_type_is_lower_case():
    for member in ServerType:
        assert member.value == member.value.lower()


def test_postgres_carries_host_port_database_and_schema():
    connection = _connection("postgresql", project_host="db.example", project_port="5432", project_db="sales")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert block["type"] == ServerType.POSTGRES
    assert block["host"] == "db.example"
    assert block["port"] == 5432
    assert block["database"] == "sales"
    assert block["schema"] == "public"
    assert block["server"]


def test_databricks_requires_catalog_and_schema():
    connection = _connection("databricks", project_db="main")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="bronze"))

    assert block["type"] == ServerType.DATABRICKS
    assert block["catalog"] == "main"
    assert block["schema"] == "bronze"


def test_a_missing_required_field_is_refused_rather_than_written_partially():
    connection = _connection("postgresql", project_host=None, project_port="5432", project_db="sales")
    with pytest.raises(ValueError, match="host"):
        build_server_block(connection, table_group=MagicMock(table_group_schema="public"))


def test_oracle_requires_host_port_and_service_name():
    connection = _connection("oracle", project_host="ora.example", project_port="1521", project_db="ORCLPDB1")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="app"))

    assert block["type"] == ServerType.ORACLE
    assert block["host"] == "ora.example"
    assert block["port"] == 1521
    assert block["serviceName"] == "ORCLPDB1"


def test_hana_requires_only_host():
    connection = _connection("sap_hana", project_host="hana.example", project_port=None, project_db=None)
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="app"))

    assert block["type"] == ServerType.HANA
    assert block["host"] == "hana.example"
    assert "port" not in block
    assert "database" not in block


def test_hana_missing_host_is_refused():
    connection = _connection("sap_hana", project_host=None)
    with pytest.raises(ValueError, match="host"):
        build_server_block(connection, table_group=MagicMock(table_group_schema="app"))


def test_bigquery_reads_the_project_id_from_the_service_account_key():
    connection = _connection(
        "bigquery", project_db=None, service_account_key={"project_id": "acme-warehouse"}
    )
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="analytics"))

    assert block["type"] == ServerType.BIGQUERY
    assert block["project"] == "acme-warehouse"
    assert block["dataset"] == "analytics"


def test_bigquery_missing_service_account_key_is_refused():
    connection = _connection("bigquery", project_db=None, service_account_key=None)
    with pytest.raises(ValueError, match="project"):
        build_server_block(connection, table_group=MagicMock(table_group_schema="analytics"))


def test_snowflake_carries_account_database_schema_and_optional_warehouse():
    connection = _connection(
        "snowflake", project_host="xy12345.snowflakecomputing.com", project_db="sales", warehouse="wh_main"
    )
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert block["type"] == ServerType.SNOWFLAKE
    assert block["account"] == "xy12345.snowflakecomputing.com"
    assert block["database"] == "sales"
    assert block["schema"] == "public"
    assert block["warehouse"] == "wh_main"


def test_snowflake_omits_warehouse_when_not_supplied():
    connection = _connection("snowflake", project_host="xy12345.snowflakecomputing.com", project_db="sales")
    connection.warehouse = None
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert "warehouse" not in block


def test_mssql_requires_host_database_and_schema():
    connection = _connection("mssql", project_host="db.example", project_port="1433", project_db="orders")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="dbo"))

    assert block["type"] == ServerType.SQLSERVER
    assert block["host"] == "db.example"
    assert block["database"] == "orders"
    assert block["schema"] == "dbo"


def test_azure_mssql_also_maps_to_sqlserver():
    connection = _connection("azure_mssql", project_host="db.example", project_port="1433", project_db="orders")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="dbo"))

    assert block["type"] == ServerType.SQLSERVER


def test_synapse_requires_host_port_and_database():
    connection = _connection("synapse_mssql", project_host="syn.example", project_port="1433", project_db="dw")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert block["type"] == ServerType.SYNAPSE
    assert block["host"] == "syn.example"
    assert block["port"] == 1433
    assert block["database"] == "dw"


def test_redshift_requires_database_and_schema():
    connection = _connection("redshift", project_host="rs.example", project_db="analytics")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert block["type"] == ServerType.REDSHIFT
    assert block["database"] == "analytics"
    assert block["schema"] == "public"
    assert block["host"] == "rs.example"


def test_an_unmapped_flavor_is_refused():
    connection = _connection("redshift_spectrum", project_host="rs.example", project_db="analytics")
    with pytest.raises(ValueError, match="redshift_spectrum"):
        build_server_block(connection, table_group=MagicMock(table_group_schema="public"))


def test_every_flavor_is_either_mapped_or_named_unmappable():
    # A flavor added without a decision here would fall through build_server_block's
    # UnmappedFlavorError and read to the user as "contracts are not supported", with no
    # sign that the omission was an oversight rather than a choice.
    assert set(FLAVOR_TO_SERVER_TYPE) | UNMAPPABLE_FLAVORS == set(SqlFlavorCode)


def test_no_flavor_is_both_mapped_and_named_unmappable():
    assert not set(FLAVOR_TO_SERVER_TYPE) & UNMAPPABLE_FLAVORS


def test_the_flavor_map_is_keyed_by_the_flavor_enum():
    assert all(isinstance(code, SqlFlavorCode) for code in FLAVOR_TO_SERVER_TYPE)


def test_duckdb_carries_its_database_file_as_the_database():
    connection = _connection(SqlFlavorCode.DUCKDB, parameters={"database_file": " /data/sales.duckdb "})
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="main"))

    assert block["type"] == ServerType.DUCKDB
    assert block["database"] == "/data/sales.duckdb"
    assert block["schema"] == "main"


def test_a_duckdb_connection_with_no_database_file_is_refused():
    connection = _connection(SqlFlavorCode.DUCKDB, parameters={})
    with pytest.raises(ValueError, match="database"):
        build_server_block(connection, table_group=MagicMock(table_group_schema="main"))


def test_the_server_types_value_is_a_plain_string_not_the_enum_member():
    # isinstance(block["type"], str) is not enough -- ServerType is a StrEnum, so a member
    # passes isinstance(x, str) and compares equal to its own value ("postgres" ==
    # ServerType.POSTGRES is True), which is exactly why every earlier test here asserting
    # `block["type"] == ServerType.POSTGRES` kept passing with the enum member still leaked
    # in. type(x) is str is the one check that tells the two apart, because it is also the
    # one check yaml.safe_dump's representer lookup actually uses.
    connection = _connection("postgresql", project_host="db.example", project_port="5432", project_db="sales")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    assert type(block["type"]) is str
    assert block["type"] == "postgres"


def test_a_server_block_survives_yaml_serialization():
    connection = _connection("postgresql", project_host="db.example", project_port="5432", project_db="sales")
    block = build_server_block(connection, table_group=MagicMock(table_group_schema="public"))

    yaml.safe_dump(block)


def test_the_pinned_api_version_is_a_member_of_the_schemas_enum():
    schema = json.loads(
        resources.files("testgen.common.odcs.schemas").joinpath("odcs-json-schema-v3.2.0.json").read_text()
    )
    assert ODCS_API_VERSION in schema["properties"]["apiVersion"]["enum"]
