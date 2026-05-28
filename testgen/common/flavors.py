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


class SqlFlavorLabel(StrEnum):
    """User-facing database-flavor labels (the ``sql_flavor`` value space)."""

    REDSHIFT = "Amazon Redshift"
    REDSHIFT_SPECTRUM = "Amazon Redshift Spectrum"
    AZURE_MSSQL = "Azure SQL Database"
    SYNAPSE_MSSQL = "Azure Synapse Analytics"
    DATABRICKS = "Databricks"
    BIGQUERY = "Google BigQuery"
    MSSQL = "Microsoft SQL Server"
    ORACLE = "Oracle"
    POSTGRESQL = "PostgreSQL"
    SAP_HANA = "SAP HANA"
    SALESFORCE_DATA360 = "Salesforce Data 360"
    SNOWFLAKE = "Snowflake"


# code → label. Label strings are written once (on the enum); this only pairs them
# with flavor codes.
FLAVOR_CODE_TO_LABEL: dict[str, SqlFlavorLabel] = {
    "redshift": SqlFlavorLabel.REDSHIFT,
    "redshift_spectrum": SqlFlavorLabel.REDSHIFT_SPECTRUM,
    "azure_mssql": SqlFlavorLabel.AZURE_MSSQL,
    "synapse_mssql": SqlFlavorLabel.SYNAPSE_MSSQL,
    "databricks": SqlFlavorLabel.DATABRICKS,
    "bigquery": SqlFlavorLabel.BIGQUERY,
    "mssql": SqlFlavorLabel.MSSQL,
    "oracle": SqlFlavorLabel.ORACLE,
    "postgresql": SqlFlavorLabel.POSTGRESQL,
    "sap_hana": SqlFlavorLabel.SAP_HANA,
    "salesforce_data360": SqlFlavorLabel.SALESFORCE_DATA360,
    "snowflake": SqlFlavorLabel.SNOWFLAKE,
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
    "mssql": "mssql",
    "oracle": "oracle",
    "postgresql": "postgresql",
    "sap_hana": "sap_hana",
    "salesforce_data360": "salesforce_data360",
    "snowflake": "snowflake",
}
