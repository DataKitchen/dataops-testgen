"""Flavor identity — the single source of truth for database-flavor display labels
and the code→family mapping.

Flavor *type* labels (e.g. "PostgreSQL", "Snowflake") are shared presentation: the
Streamlit connections page feeds them to its JS component via ``FLAVOR_OPTIONS`` and
the MCP tools accept/return them as the ``sql_flavor`` value. Both surfaces derive
from here so the labels are written exactly once.

This module is intentionally pure data (no I/O, no Streamlit, no SQLAlchemy) so it
can be imported from the UI, the MCP layer, and common services without cycles.

(The per-flavor *connection-parameter* field labels and requirement rules are a
different, MCP-only concern and live in ``mcp/tools/common.py`` — they're hardcoded
in the JS form, not sourced from Python.)
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
