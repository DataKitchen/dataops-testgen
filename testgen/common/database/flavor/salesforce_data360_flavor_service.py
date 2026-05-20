from typing import Any

from sqlalchemy.dialects import registry
from sqlalchemy.pool import StaticPool

from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams

# Register the dialect so create_engine("salesforce_data360://") works
# without requiring an installed entry point.
registry.register("salesforce_data360", "testgen.common.database.salesforce_data360_dialect", "SalesforceData360Dialect")

# Mapping from Data 360 metadata types to TestGen general_type codes.
# Data 360's metadata API returns a small fixed vocabulary — these 6 are all that
# have been observed against profiled DMOs and DLOs. Unknown types preserve the
# raw metadata string as column_type and fall through to general_type "X" in
# get_schema_columns(), matching get_schema_ddf.sql behavior for other flavors.
_TYPE_MAP: dict[str, tuple[str, str, bool]] = {
    # metadata_type → (column_type, general_type, is_decimal)
    "STRING": ("varchar", "A", False),
    "NUMBER": ("numeric", "N", True),
    "BIGINT": ("bigint", "N", False),
    "BOOLEAN": ("boolean", "B", False),
    "DATE": ("date", "D", False),
    "DATE_TIME": ("datetime", "D", False),
}


class SalesforceData360FlavorService(FlavorService):

    concat_operator = "||"
    quote_character = '"'
    escaped_single_quote = "''"
    escaped_underscore = "\\_"
    escape_clause = ""
    varchar_type = "VARCHAR(1000)"
    default_uppercase = False
    test_query = "SELECT 1"
    url_scheme = "salesforce_data360"
    qualifies_table_refs_with_schema = False
    metadata_via_api = True

    def get_connection_string(self, _params: ResolvedConnectionParams) -> str:
        return "salesforce_data360://"

    def get_connection_string_from_fields(self, _params: ResolvedConnectionParams) -> str:
        return "salesforce_data360://"

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:
        # Map Connection model fields to salesforce-cdp-connector kwargs.
        #   project_host       → login_url   (org My Domain URL)
        #   project_user       → client_id   (Consumer Key from External Client App)
        #   password           → client_secret (Client Credentials flow)
        #   project_db         → username    (JWT Bearer flow)
        #   private_key        → private_key (JWT Bearer flow)
        #   connect_by_key     → True = JWT, False = Client Credentials
        #   table_group_schema → dataspace   (Data 360 Data Space — scopes the CDP token)
        args: dict[str, Any] = {
            "login_url": params.host,
            "client_id": params.username,
        }

        # Connection-only contexts (Test Connection from the connection wizard) have
        # no table group yet, so dbschema is empty — the connector then defaults to
        # the org's default Data Space, which is fine for "can we authenticate?".
        # Table-group-scoped contexts (profiling, test execution, preview) supply
        # the Data Space and the resulting CDP token is restricted to it.
        if params.dbschema:
            args["dataspace"] = params.dbschema

        if params.connect_by_key and params.private_key:
            args["username"] = params.dbname
            args["private_key"] = params.private_key
        else:
            args["client_secret"] = params.password

        return args

    def get_engine_args(self, _params: ResolvedConnectionParams) -> dict[str, Any]:
        return {
            "pool_pre_ping": False,
            "poolclass": StaticPool,
        }

    def get_pre_connection_queries(self, _params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:
        return []

    def get_schema_columns(self, params: ResolvedConnectionParams, schema: str) -> list[ColumnChars] | None:
        """Fetch column metadata via the salesforce-cdp-connector metadata API.

        Data 360 has no information_schema — this method replaces the SQL-based
        schema discovery for this flavor.
        """
        from salesforcecdpconnector.connection import SalesforceCDPConnection

        connect_args = self.get_connect_args(params)
        conn = SalesforceCDPConnection(**connect_args)

        try:
            tables = conn.list_tables()
        finally:
            conn.close()

        columns: list[ColumnChars] = []
        for table in tables:
            for ordinal, field in enumerate(table.fields, start=1):
                if not field.name:
                    continue

                meta_type = (field.type or "").upper()
                mapped = _TYPE_MAP.get(meta_type)
                if mapped is not None:
                    column_type, general_type, is_decimal = mapped
                else:
                    column_type, general_type, is_decimal = meta_type.lower(), "X", False

                columns.append(ColumnChars(
                    schema_name=schema,
                    table_name=table.name,
                    column_name=field.name,
                    column_type=column_type,
                    db_data_type=meta_type,
                    ordinal_position=ordinal,
                    general_type=general_type,
                    is_decimal=is_decimal,
                ))

        return columns
