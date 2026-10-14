"""The ODCS server block for a contract, built from a connection and its table group."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlparse

from testgen.common.database.file_declarations import BASE_PATH_PARAMETER
from testgen.common.database.flavor.duckdb_object_storage import (
    REGION_PARAMETER,
    STORAGE_ACCOUNT_PARAMETER,
    store_for,
)
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
# nor ``CUSTOM_FIELDS`` fails the completeness test, so a new flavor forces the choice
# between a typed entry and a ``custom`` one.
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
    ServerType.DUCKDB: ("database",),
}

OPTIONAL_FIELDS: dict[ServerType, tuple[str, ...]] = {
    ServerType.SNOWFLAKE: ("warehouse",),
    ServerType.HANA: ("port", "database", "schema"),
    ServerType.REDSHIFT: ("host",),
    ServerType.DUCKDB: ("schema",),
}


# Flavors with no faithful ODCS server type, and the ``CustomServer`` fields their ``custom``
# entry carries. ``redshift_spectrum`` reads S3-backed external tables rather than a
# Redshift-native store, ``onelake_mssql`` is Microsoft Fabric storage, ``salesforce_data360`` has
# no counterpart in the enum at all, and ``files``, ``s3`` and ``azure_blob`` set a format per
# declared table where the ``local``, ``s3`` and ``azure`` server types take one location and one
# format for the whole store. A Data 360 connection's host is its org's login URL, written as
# ``endpointUrl`` when it is an absolute URL (the schema requires one there) and as ``host``
# otherwise; its database field holds the username, so it is never written. A flavor with a server type that
# falls back to ``custom`` carries that type's own fields.
CUSTOM_FIELDS: dict[SqlFlavorCode, tuple[str, ...]] = {
    SqlFlavorCode.REDSHIFT_SPECTRUM: ("host", "port", "database", "schema"),
    SqlFlavorCode.ONELAKE_MSSQL: ("host", "port", "database", "schema"),
    SqlFlavorCode.SALESFORCE_DATA360: ("endpointUrl", "host"),
    SqlFlavorCode.FILES: ("path",),
    SqlFlavorCode.S3: ("location", "region"),
    SqlFlavorCode.AZURE_BLOB: ("account", "location"),
}


@dataclass(frozen=True)
class CustomServerReason:
    """Why a server entry is ``custom``: the flavor has no server type (``server_type`` is
    ``None``), or the connection does not supply ``missing_fields``, which ``server_type`` requires."""

    server_type: ServerType | None
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServerBlock:
    entry: dict[str, Any]
    custom_reason: CustomServerReason | None = None


def build_server_block(connection: Connection, table_group: TableGroup) -> ServerBlock:
    """The server entry for a contract's document, built from its connection and table group.

    The entry is typed when the flavor has an ODCS server type and the connection supplies every
    field that type requires. Otherwise it is ``custom``, carrying whichever of its fields the
    connection supplies, and ``custom_reason`` says why.
    """
    flavor = SqlFlavorCode(connection.sql_flavor_code)
    available = _fields_for(flavor, connection, table_group)
    server_type = FLAVOR_TO_SERVER_TYPE.get(flavor)

    if server_type is None:
        return ServerBlock(
            _entry(connection, ServerType.CUSTOM, CUSTOM_FIELDS[flavor], available),
            CustomServerReason(server_type=None),
        )

    fields = REQUIRED_FIELDS[server_type] + OPTIONAL_FIELDS.get(server_type, ())
    if missing := tuple(name for name in REQUIRED_FIELDS[server_type] if available.get(name) in (None, "")):
        return ServerBlock(
            _entry(connection, ServerType.CUSTOM, fields, available),
            CustomServerReason(server_type=server_type, missing_fields=missing),
        )
    return ServerBlock(_entry(connection, server_type, fields, available))


def _entry(
    connection: Connection, server_type: ServerType, fields: tuple[str, ...], available: dict[str, Any]
) -> dict[str, Any]:
    # `.value`, not `server_type` itself: the result is document data destined for
    # `yaml.safe_dump`, which raises on an unregistered type -- and a `StrEnum` member, though
    # it compares equal to its own value and passes `isinstance(x, str)`, is not `str` by
    # `type()`, which is what `yaml.safe_dump`'s representer lookup actually uses.
    entry: dict[str, Any] = {"server": connection.connection_name, "type": server_type.value}
    for name in fields:
        if available.get(name) not in (None, ""):
            entry[name] = available[name]
    return entry


def _fields_for(flavor: SqlFlavorCode, connection: Connection, table_group: TableGroup) -> dict[str, Any]:
    schema = table_group.table_group_schema
    parameters = connection.parameters or {}

    project_id = None
    if flavor is SqlFlavorCode.BIGQUERY and connection.service_account_key:
        project_id = connection.service_account_key.get("project_id")

    database = connection.project_db
    if flavor is SqlFlavorCode.DUCKDB:
        # A DuckDB connection names a file rather than a server-side database, and that path
        # is the only thing identifying which store the contract covers.
        database = _text(parameters, "database_file")

    host = connection.project_host
    account = connection.project_host
    if flavor is SqlFlavorCode.AZURE_BLOB:
        account = _text(parameters, STORAGE_ACCOUNT_PARAMETER)

    endpoint_url = None
    if flavor is SqlFlavorCode.SALESFORCE_DATA360 and host:
        login_url = urlparse(host)
        if login_url.scheme and login_url.netloc:
            endpoint_url, host = _as_uri(host), None

    store = store_for(flavor)
    return {
        "host": host,
        "port": int(connection.project_port) if connection.project_port else None,
        "database": database,
        "catalog": connection.project_db,
        "project": project_id,
        "dataset": schema,
        "account": account,
        "warehouse": getattr(connection, "warehouse", None),
        "schema": schema,
        "serviceName": connection.project_db,
        "path": _text(parameters, BASE_PATH_PARAMETER),
        "location": _as_uri(store.base_location(parameters)) if store else None,
        "region": _text(parameters, REGION_PARAMETER),
        "endpointUrl": endpoint_url,
    }


# RFC 3986 reserved characters, and `%` so an escape the text already carries is kept.
_URI_SAFE = ":/?#[]@!$&'()*+,;=%"


def _as_uri(text: str) -> str | None:
    """``text`` with every character a URI cannot carry percent-encoded, or ``None`` when empty.

    A ``%`` is kept as written, so a literal one cannot be told apart from an escape."""
    return quote(text, safe=_URI_SAFE) or None


def _text(parameters: dict[str, Any], key: str) -> str | None:
    value = parameters.get(key)
    return (value.strip() or None) if isinstance(value, str) else None
