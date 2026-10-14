from urllib.parse import quote_plus

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from snowflake.sqlalchemy import URL

from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams, base_type_name


class SnowflakeFlavorService(FlavorService):

    escaped_underscore = "\\\\_"
    literal_escapes_backslash = True
    escape_clause = "ESCAPE '\\\\'"
    default_uppercase = True
    url_scheme = "snowflake"

    supports_approx_percentile = True

    supports_value_hash = True
    float_types = frozenset({"float", "float4", "float8", "double", "double precision", "real"})
    wide_decimal_type = "NUMBER(38,0)"

    def hex_to_wide_decimal(self, hex_expr: str) -> str:
        return f"CAST(TO_NUMBER(UPPER({hex_expr}), 'XXXXXXXXXXXXXX') AS {self.wide_decimal_type})"

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        if base_type_name(column.db_data_type) in ("timestamp_tz", "timestamp_ltz"):
            return f"CAST(CONVERT_TIMEZONE('UTC', {column_ref}) AS TIMESTAMP_NTZ)"
        return f"CAST({column_ref} AS TIMESTAMP_NTZ)"

    def format_timestamp(self, timestamp_expr: str) -> str:
        return f"TO_CHAR({timestamp_expr}, 'YYYY-MM-DD HH24:MI:SS')"

    def epoch_seconds(self, timestamp_expr: str) -> str:
        return f"DATEDIFF(second, CAST('1970-01-01' AS TIMESTAMP_NTZ), {timestamp_expr})"

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:
        if params.connect_by_key:
            # https://docs.snowflake.com/en/developer-guide/python-connector/sqlalchemy#key-pair-authentication-support
            private_key_passphrase = params.private_key_passphrase.encode() if params.private_key_passphrase else None
            private_key = serialization.load_pem_private_key(
                params.private_key.encode(),
                password=private_key_passphrase,
                backend=default_backend(),
            )

            private_key_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )

            return {"private_key": private_key_bytes}
        return {}

    def get_connection_string_head(self, params: ResolvedConnectionParams) -> str:
        if params.connect_by_key:
            return f"{self.url_scheme}://{params.username}@"
        else:
            return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        # SNOWFLAKE FORMAT:  strConnect = 'flavor://username:password@host/database'
        #   optionally + '/[schema]' + '?warehouse=xxx'
        #   NOTE:  Snowflake host should NOT include ".snowflakecomputing.com"

        account, _ = params.host.split(".", maxsplit=1) if "." in params.host else ("", "")
        host = params.host
        if ".snowflakecomputing.com" not in host:
            host = f"{host}.snowflakecomputing.com"

        extra_params = {}
        if params.warehouse:
            extra_params["warehouse"] = params.warehouse

        connection_url = URL(
            host=host,
            port=int(params.port if str(params.port).isdigit() else 443),
            account=account,
            user=params.username,
            password="" if params.connect_by_key else params.password,
            database=params.dbname,
            schema=params.dbschema or "",
            **extra_params,
        )

        return connection_url

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:
        queries: list[tuple[str, dict | None]] = [
            ("ALTER SESSION SET MULTI_STATEMENT_COUNT = 0;", None),
            ("ALTER SESSION SET WEEK_START = 7;", None),
        ]
        # A connection from fields carries the table group's schema in its URL. A user-supplied URL does not,
        # so an unqualified table in a custom query would not resolve in the table group's schema.
        if params.connect_by_url and params.dbschema:
            quoted_schema = params.dbschema.replace('"', '""')
            queries.append((f'USE SCHEMA "{quoted_schema}";', None))
        return queries
