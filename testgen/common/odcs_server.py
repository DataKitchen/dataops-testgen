"""The ODCS server block for a contract, built from a connection and its table group."""

from enum import StrEnum
from typing import Any

from testgen.common.flavors import SqlFlavorCode
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup

# The ODCS release the documents this module writes are authored against. Pinned rather than
# tracking latest: upstream republishes schema files in place, and some of those edits change
# what validates.
ODCS_API_VERSION = "v3.2.0"

ODCS_KIND = "DataContract"


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


# Flavor -> ODCS server type. Confidently mapped flavors only: a flavor in neither this map
# nor ``UNMAPPABLE_FLAVORS`` fails the completeness test rather than silently refusing at
# runtime.
FLAVOR_TO_SERVER_TYPE: dict[SqlFlavorCode, ServerType] = {
    SqlFlavorCode.REDSHIFT: ServerType.REDSHIFT,
    SqlFlavorCode.AZURE_MSSQL: ServerType.SQLSERVER,
    SqlFlavorCode.SYNAPSE_MSSQL: ServerType.SYNAPSE,
    SqlFlavorCode.DATABRICKS: ServerType.DATABRICKS,
    SqlFlavorCode.DUCKDB: ServerType.DUCKDB,
    SqlFlavorCode.BIGQUERY: ServerType.BIGQUERY,
    SqlFlavorCode.MSSQL: ServerType.SQLSERVER,
    SqlFlavorCode.ORACLE: ServerType.ORACLE,
    SqlFlavorCode.POSTGRESQL: ServerType.POSTGRES,
    SqlFlavorCode.SAP_HANA: ServerType.HANA,
    SqlFlavorCode.SNOWFLAKE: ServerType.SNOWFLAKE,
}

# Flavors with no faithful ODCS server type. ``redshift_spectrum`` reads S3-backed external
# tables rather than a Redshift-native store, ``onelake_mssql`` is Microsoft Fabric storage,
# ``salesforce_data360`` has no counterpart in the enum at all, and ``files`` sets a format per
# declared table where the ``local`` server type takes one path and one format for the whole store.
UNMAPPABLE_FLAVORS: frozenset[SqlFlavorCode] = frozenset({
    SqlFlavorCode.REDSHIFT_SPECTRUM,
    SqlFlavorCode.ONELAKE_MSSQL,
    SqlFlavorCode.SALESFORCE_DATA360,
    SqlFlavorCode.FILES,
})

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
    ServerType.DUCKDB: ("database", "schema"),
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
    server_type = FLAVOR_TO_SERVER_TYPE.get(SqlFlavorCode(connection.sql_flavor_code))
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

    database = connection.project_db
    if server_type is ServerType.DUCKDB:
        # A DuckDB connection names a file rather than a server-side database, and that path
        # is the only thing identifying which store the contract covers.
        database = ((connection.parameters or {}).get("database_file") or "").strip() or None

    return {
        "host": connection.project_host,
        "port": int(connection.project_port) if connection.project_port else None,
        "database": database,
        "catalog": connection.project_db,
        "project": project_id,
        "dataset": schema,
        "account": connection.project_host,
        "warehouse": getattr(connection, "warehouse", None),
        "schema": schema,
        "serviceName": connection.project_db,
    }
