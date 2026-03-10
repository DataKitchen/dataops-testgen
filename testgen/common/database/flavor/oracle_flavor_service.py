import sys
from urllib.parse import quote_plus

import oracledb

from testgen.common.database.flavor.flavor_service import FlavorService

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

    def get_connection_string_head(self):
        return f"oracle://{self.username}:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        return f"oracle://{self.username}:{quote_plus(self.password)}@{self.host}:{self.port}?service_name={self.dbname}"

    def get_pre_connection_queries(self):
        return [
            ("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS'", None),
        ]

    def get_connect_args(self) -> dict:
        return {}
