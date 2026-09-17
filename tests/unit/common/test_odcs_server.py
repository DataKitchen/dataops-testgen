from unittest.mock import MagicMock

import pytest

from testgen.common.odcs_server import ServerType, build_server_block

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
