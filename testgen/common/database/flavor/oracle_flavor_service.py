import sys
from urllib.parse import quote_plus

import oracledb

from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams

# https://stackoverflow.com/a/74105559
oracledb.version = "8.3.0"
sys.modules["cx_Oracle"] = oracledb


class OracleFlavorService(FlavorService):

    escaped_underscore = "\\_"
    escape_clause = "ESCAPE '\\'"
    varchar_type = "VARCHAR2(1000)"
    default_uppercase = True
    row_limiting_clause = "fetch"
    test_query = "SELECT 1 FROM DUAL"
    url_scheme = "oracle"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@{params.host}:{params.port}?service_name={params.dbname}"

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:  # noqa: ARG002
        return [
            ("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS'", None),
        ]

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:  # noqa: ARG002
        return {}
