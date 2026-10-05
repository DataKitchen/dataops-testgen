"""Flavor identity — the single source of truth for database-flavor display labels
and the code→family mapping.

Flavor *type* labels (e.g. "PostgreSQL", "Snowflake") are shared presentation: the
Streamlit connections page feeds them to its JS component via ``FLAVOR_OPTIONS`` and
the MCP tools accept/return them as the ``sql_flavor`` value. Both surfaces derive
from here so the labels are written exactly once.

This module is intentionally pure data (no I/O, no Streamlit, no SQLAlchemy) so it
can be imported from the UI, the MCP layer, and common services without cycles.

(The per-flavor *connection-parameter* field labels and requirement rules are a
different concern and live in ``common/connection_schema.py``.)
"""

from __future__ import annotations

from enum import StrEnum


class SqlFlavorCode(StrEnum):
    """Stored ``sql_flavor_code`` values. Each code resolves to a family via
    ``FLAVOR_CODE_TO_FAMILY``."""

    REDSHIFT = "redshift"
    REDSHIFT_SPECTRUM = "redshift_spectrum"
    AZURE_MSSQL = "azure_mssql"
    SYNAPSE_MSSQL = "synapse_mssql"
    DATABRICKS = "databricks"
    DUCKDB = "duckdb"
    FILES = "files"
    S3 = "s3"
    AZURE_BLOB = "azure_blob"
    BIGQUERY = "bigquery"
    ONELAKE_MSSQL = "onelake_mssql"
    MSSQL = "mssql"
    ORACLE = "oracle"
    POSTGRESQL = "postgresql"
    SAP_HANA = "sap_hana"
    SALESFORCE_DATA360 = "salesforce_data360"
    SNOWFLAKE = "snowflake"


class SqlFlavorLabel(StrEnum):
    """User-facing database-flavor labels (the ``sql_flavor`` value space)."""

    REDSHIFT = "Amazon Redshift"
    REDSHIFT_SPECTRUM = "Amazon Redshift Spectrum"
    AZURE_MSSQL = "Azure SQL Database"
    SYNAPSE_MSSQL = "Azure Synapse Analytics"
    DATABRICKS = "Databricks"
    DUCKDB = "DuckDB"
    FILES = "Local Files"
    S3 = "Amazon S3"
    AZURE_BLOB = "Azure Blob Storage"
    BIGQUERY = "Google BigQuery"
    ONELAKE_MSSQL = "Microsoft OneLake"
    MSSQL = "Microsoft SQL Server"
    ORACLE = "Oracle"
    POSTGRESQL = "PostgreSQL"
    SAP_HANA = "SAP HANA"
    SALESFORCE_DATA360 = "Salesforce Data 360"
    SNOWFLAKE = "Snowflake"


# code → label. Label strings are written once (on the enum); this only pairs them
# with flavor codes.
FLAVOR_CODE_TO_LABEL: dict[SqlFlavorCode, SqlFlavorLabel] = {
    SqlFlavorCode.REDSHIFT: SqlFlavorLabel.REDSHIFT,
    SqlFlavorCode.REDSHIFT_SPECTRUM: SqlFlavorLabel.REDSHIFT_SPECTRUM,
    SqlFlavorCode.AZURE_MSSQL: SqlFlavorLabel.AZURE_MSSQL,
    SqlFlavorCode.SYNAPSE_MSSQL: SqlFlavorLabel.SYNAPSE_MSSQL,
    SqlFlavorCode.DATABRICKS: SqlFlavorLabel.DATABRICKS,
    SqlFlavorCode.DUCKDB: SqlFlavorLabel.DUCKDB,
    SqlFlavorCode.FILES: SqlFlavorLabel.FILES,
    SqlFlavorCode.S3: SqlFlavorLabel.S3,
    SqlFlavorCode.AZURE_BLOB: SqlFlavorLabel.AZURE_BLOB,
    SqlFlavorCode.BIGQUERY: SqlFlavorLabel.BIGQUERY,
    SqlFlavorCode.ONELAKE_MSSQL: SqlFlavorLabel.ONELAKE_MSSQL,
    SqlFlavorCode.MSSQL: SqlFlavorLabel.MSSQL,
    SqlFlavorCode.ORACLE: SqlFlavorLabel.ORACLE,
    SqlFlavorCode.POSTGRESQL: SqlFlavorLabel.POSTGRESQL,
    SqlFlavorCode.SAP_HANA: SqlFlavorLabel.SAP_HANA,
    SqlFlavorCode.SALESFORCE_DATA360: SqlFlavorLabel.SALESFORCE_DATA360,
    SqlFlavorCode.SNOWFLAKE: SqlFlavorLabel.SNOWFLAKE,
}

# code → family (multiple codes can share one engine family, e.g. the two Azure
# variants both map to "mssql").
FLAVOR_CODE_TO_FAMILY: dict[str, str] = {
    "redshift": "redshift",
    "redshift_spectrum": "redshift_spectrum",
    "azure_mssql": "mssql",
    "synapse_mssql": "mssql",
    "databricks": "databricks",
    "duckdb": "duckdb",
    "files": "duckdb",
    "s3": "duckdb",
    "azure_blob": "duckdb",
    "bigquery": "bigquery",
    "onelake_mssql": "mssql",
    "mssql": "mssql",
    "oracle": "oracle",
    "postgresql": "postgresql",
    "sap_hana": "sap_hana",
    "salesforce_data360": "salesforce_data360",
    "snowflake": "snowflake",
}

# Stored ``sql_flavor`` values (the distinct families).
FLAVOR_FAMILIES: frozenset[str] = frozenset(FLAVOR_CODE_TO_FAMILY.values())

# Flavors that run their engine inside the TestGen process rather than on a server reachable over
# the network. Every engine instance sizes its memory budget against the whole container as though
# it were alone there, so instances that run at once oversubscribe the container's memory.
IN_PROCESS_FLAVOR_CODES: frozenset[str] = frozenset({
    SqlFlavorCode.DUCKDB,
    SqlFlavorCode.FILES,
    SqlFlavorCode.S3,
    SqlFlavorCode.AZURE_BLOB,
})

# ``max_threads`` sizes the pool TestGen fans per-column queries across, and every checkout of an
# in-process engine is another engine instance over the same cores — several times the peak memory
# for no additional throughput.
#
# The engine's own intra-query parallelism is a separate setting TestGen does not configure:
# DuckDB sizes its thread pool from the detected CPU count whatever this value says.
FLAVOR_FIXED_MAX_THREADS: dict[str, int] = dict.fromkeys(IN_PROCESS_FLAVOR_CODES, 1)


def runs_in_process(sql_flavor_code: str | None) -> bool:
    """Whether a flavor's engine runs inside the TestGen process."""
    return sql_flavor_code in IN_PROCESS_FLAVOR_CODES


def fixed_max_threads(sql_flavor_code: str | None) -> int | None:
    """The thread count a flavor requires, or None when the connection's own setting applies."""
    return FLAVOR_FIXED_MAX_THREADS.get(sql_flavor_code) if sql_flavor_code else None


# The schema every table group on a flavor code stores, where the user does not pick one. Every
# declaration on the files code becomes a view in DuckDB's default schema, so the form does not
# show the field and the value is written here instead.
FLAVOR_FIXED_TABLE_GROUP_SCHEMA: dict[str, str] = {
    SqlFlavorCode.FILES: "main",
    SqlFlavorCode.S3: "main",
    SqlFlavorCode.AZURE_BLOB: "main",
}

# Flavors whose table group lists its tables as files instead of having them discovered from a
# catalog. Separate from the fixed-schema registry above: a flavor can pin a schema and still read
# a real catalog.
FLAVOR_DECLARES_FILES: frozenset[str] = frozenset({SqlFlavorCode.FILES, SqlFlavorCode.S3, SqlFlavorCode.AZURE_BLOB})


def fixed_table_group_schema(sql_flavor_code: str | None) -> str | None:
    """The schema a flavor fixes for every table group on it, or None when the user picks one."""
    return FLAVOR_FIXED_TABLE_GROUP_SCHEMA.get(sql_flavor_code) if sql_flavor_code else None


def declares_files(sql_flavor_code: str | None) -> bool:
    """Whether a flavor's tables are declared as files rather than discovered from a catalog."""
    return sql_flavor_code in FLAVOR_DECLARES_FILES if sql_flavor_code else False


class TableGroupSchemaLabel(StrEnum):
    """User-facing names for the value a table group stores in ``table_group_schema``."""

    SCHEMA = "Schema"
    DATA_SPACE = "Data Space"


# What a flavor code calls the value its table groups store in ``table_group_schema``. A code
# absent from this map calls it "Schema". A code mapped to None has no schema a user can name, so
# nothing is reported for it -- the stored value is still needed to reach the target.
FLAVOR_TABLE_GROUP_SCHEMA_LABEL: dict[str, TableGroupSchemaLabel | None] = {
    SqlFlavorCode.FILES: None,
    SqlFlavorCode.S3: None,
    SqlFlavorCode.AZURE_BLOB: None,
    SqlFlavorCode.SALESFORCE_DATA360: TableGroupSchemaLabel.DATA_SPACE,
}


def table_group_schema_label(sql_flavor_code: str | None) -> str | None:
    """The user-facing name for a table group's schema, or None when the flavor reports none."""
    if sql_flavor_code in FLAVOR_TABLE_GROUP_SCHEMA_LABEL:
        label = FLAVOR_TABLE_GROUP_SCHEMA_LABEL[sql_flavor_code]
        return str(label) if label is not None else None
    return str(TableGroupSchemaLabel.SCHEMA)


def reports_table_group_schema(sql_flavor_code: str | None) -> bool:
    """Whether a flavor's table group has a schema worth reporting to the user."""
    return table_group_schema_label(sql_flavor_code) is not None
