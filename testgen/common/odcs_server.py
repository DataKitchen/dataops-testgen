"""The ODCS server block for a contract, built from a connection and its table group."""

from enum import StrEnum
from typing import Any

from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup


class ServerType(StrEnum):
    """The ``type`` of an ODCS server.

    Values are the full, lower-case ``Server.type`` enum from the Open Data Contract
    Standard schema (bitol-io/open-data-contract-standard), not just the members
    TestGen maps a flavor to — an unrecognized value here would be exactly the invalid
    document this module exists to prevent.
    """

    API = "api"
    ATHENA = "athena"
    AZURE = "azure"
    BIGQUERY = "bigquery"
    BTRIEVE = "btrieve"
    CLICKHOUSE = "clickhouse"
    DATABRICKS = "databricks"
    DENODO = "denodo"
    DREMIO = "dremio"
    DUCKDB = "duckdb"
    EXASOL = "exasol"
    FASTOBJECTS = "fastobjects"
    GLUE = "glue"
    HANA = "hana"
    CLOUDSQL = "cloudsql"
    DB2 = "db2"
    HIVE = "hive"
    ICEBERG = "iceberg"
    IMPALA = "impala"
    INFORMIX = "informix"
    INGRES = "ingres"
    KAFKA = "kafka"
    KINESIS = "kinesis"
    LOCAL = "local"
    MYSQL = "mysql"
    ORACLE = "oracle"
    POET = "poet"
    POSTGRESQL = "postgresql"
    POSTGRES = "postgres"
    PRESTO = "presto"
    PUBSUB = "pubsub"
    REDSHIFT = "redshift"
    S3 = "s3"
    SFTP = "sftp"
    SNOWFLAKE = "snowflake"
    SQLSERVER = "sqlserver"
    SYNAPSE = "synapse"
    TERADATA = "teradata"
    TRINO = "trino"
    VECTORWISE = "vectorwise"
    VERSANT = "versant"
    VERTICA = "vertica"
    ZEN = "zen"
    CUSTOM = "custom"


# code -> ODCS server type. Confidently mapped flavors only: a flavor left out raises in
# ``build_server_block`` rather than writing a guessed type. ``redshift_spectrum`` (its
# tables are S3-backed, not a Redshift-native store), ``onelake_mssql`` (Microsoft Fabric
# storage, not a member of the ODCS server-type enum) and ``salesforce_data360`` (no ODCS
# server type corresponds to it) are deliberately absent.
FLAVOR_TO_SERVER_TYPE: dict[str, ServerType] = {
    "redshift": ServerType.REDSHIFT,
    "azure_mssql": ServerType.SQLSERVER,
    "synapse_mssql": ServerType.SYNAPSE,
    "databricks": ServerType.DATABRICKS,
    "bigquery": ServerType.BIGQUERY,
    "mssql": ServerType.SQLSERVER,
    "oracle": ServerType.ORACLE,
    "postgresql": ServerType.POSTGRES,
    "sap_hana": ServerType.HANA,
    "snowflake": ServerType.SNOWFLAKE,
}

# Every server carries ``server``; these are the fields each type requires beyond it.
REQUIRED_FIELDS: dict[ServerType, tuple[str, ...]] = {
    ServerType.POSTGRES: ("host", "port", "database", "schema"),
    ServerType.SQLSERVER: ("host", "database", "schema"),
    ServerType.SYNAPSE: ("host", "port", "database"),
    ServerType.SNOWFLAKE: ("account", "database", "schema"),
    ServerType.BIGQUERY: ("project", "dataset"),
    ServerType.DATABRICKS: ("catalog", "schema"),
    ServerType.ORACLE: ("host", "port", "serviceName"),
    ServerType.HANA: ("host",),
    ServerType.REDSHIFT: ("database", "schema"),
}

OPTIONAL_FIELDS: dict[ServerType, tuple[str, ...]] = {
    ServerType.SNOWFLAKE: ("warehouse",),
    ServerType.HANA: ("port", "database", "schema"),
    ServerType.REDSHIFT: ("host",),
}


class UnmappedFlavorError(ValueError):
    """Raised when a connection's flavor maps to no ODCS server type."""


def build_server_block(connection: Connection, table_group: TableGroup) -> dict[str, Any]:
    """The server entry for a contract's document.

    Raises ``UnmappedFlavorError`` when the flavor maps to no ODCS server type, and
    ``ValueError`` naming every required field the connection does not supply, rather than
    emitting a block the schema will reject.
    """
    server_type = FLAVOR_TO_SERVER_TYPE.get(connection.sql_flavor_code)
    if server_type is None:
        raise UnmappedFlavorError(f"No server type for flavor {connection.sql_flavor_code!r}.")

    available = _fields_for(server_type, connection, table_group)
    missing = [name for name in REQUIRED_FIELDS[server_type] if available.get(name) in (None, "")]
    if missing:
        raise ValueError(
            f"The connection does not supply {', '.join(missing)}, which {server_type} requires."
        )

    block: dict[str, Any] = {"server": connection.connection_name, "type": server_type}
    for name in REQUIRED_FIELDS[server_type] + OPTIONAL_FIELDS.get(server_type, ()):
        if available.get(name) not in (None, ""):
            block[name] = available[name]
    return block


def _fields_for(server_type: ServerType, connection: Connection, table_group: TableGroup) -> dict[str, Any]:
    schema = table_group.table_group_schema

    project_id = None
    if server_type is ServerType.BIGQUERY and connection.service_account_key:
        project_id = connection.service_account_key.get("project_id")

    return {
        "host": connection.project_host,
        "port": int(connection.project_port) if connection.project_port else None,
        "database": connection.project_db,
        "catalog": connection.project_db,
        "project": project_id,
        "dataset": schema,
        "account": connection.project_host,
        "warehouse": getattr(connection, "warehouse", None),
        "schema": schema,
        "serviceName": connection.project_db,
    }
