from urllib.parse import quote_plus

from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.flavor_service import (
    FlavorService,
    ResolvedConnectionParams,
    base_type_name,
    exact_float_canonical,
)


class DatabricksFlavorService(FlavorService):

    quote_character = "`"
    escaped_single_quote = "\\'"
    literal_escapes_backslash = True
    varchar_type = "STRING"
    url_scheme = "databricks"

    supports_approx_percentile = True

    distinct_countable_x_types = frozenset({"binary"})

    supports_value_hash = True
    float_types = frozenset({"double", "float", "real"})
    double_type = "DOUBLE"

    def canonical_number(self, column_ref: str, is_float: bool) -> str:
        if is_float:
            # A direct cast keeps only 17 significant digits. DIV returns a BIGINT; a decimal quotient
            # carries six decimal places, which leaves too few whole digits for the scaled value.
            canonical = exact_float_canonical(
                column_ref, self.double_type, "DECIMAL(38,0)", lambda a, b: f"(({a}) DIV {b})"
            )
            return f"CAST(CAST({canonical} AS DECIMAL(38,0)) AS {self.varchar_type})"
        return super().canonical_number(column_ref, is_float)

    def hex_to_wide_decimal(self, hex_expr: str) -> str:
        return f"CAST(CONV({hex_expr}, 16, 10) AS {self.wide_decimal_type})"

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        # A TIMESTAMP is an instant rendered in the session time zone; TIMESTAMP_NTZ is a wall-clock time
        if base_type_name(column.db_data_type) == "timestamp":
            return f"CAST(TO_UTC_TIMESTAMP({column_ref}, CURRENT_TIMEZONE()) AS TIMESTAMP_NTZ)"
        return f"CAST({column_ref} AS TIMESTAMP_NTZ)"

    def format_timestamp(self, timestamp_expr: str) -> str:
        return f"DATE_FORMAT({timestamp_expr}, 'yyyy-MM-dd HH:mm:ss')"

    def epoch_seconds(self, timestamp_expr: str) -> str:
        # From the wall-clock fields, which a TIMESTAMP_NTZ keeps independent of the session time zone
        return (
            f"(CAST(UNIX_DATE(CAST({timestamp_expr} AS DATE)) AS BIGINT) * 86400 + HOUR({timestamp_expr}) * 3600"
            f" + MINUTE({timestamp_expr}) * 60 + SECOND({timestamp_expr}))"
        )

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:
        if params.dbname:
            return [(f"USE CATALOG `{params.dbname}`", None)]
        return []

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:
        args = {}
        if params.dbname:
            args["catalog"] = params.dbname
        if params.connect_by_key:
            args["credentials_provider"] = self._get_oauth_credentials_provider(params)
        return args

    def get_connection_string_head(self, params: ResolvedConnectionParams) -> str:
        if params.connect_by_key:
            return f"{self.url_scheme}://oauth:@"
        return f"{self.url_scheme}://token:{quote_plus(params.password)}@"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        if params.connect_by_key:
            return (
                f"{self.url_scheme}://oauth:@{params.host}:{params.port}/{params.dbname}"
                f"?http_path={params.http_path}&catalog={params.dbname}"
            )
        return (
            f"{self.url_scheme}://token:{quote_plus(params.password)}@{params.host}:{params.port}/{params.dbname}"
            f"?http_path={params.http_path}&catalog={params.dbname}"
        )

    def _get_oauth_credentials_provider(self, params: ResolvedConnectionParams):
        from databricks.sdk.core import Config, oauth_service_principal

        config = Config(
            host=f"https://{params.host}",
            client_id=params.username,
            client_secret=params.password,
        )
        # oauth_service_principal(config) returns an OAuthCredentialsProvider,
        # which is callable: provider() -> Dict[str, str] (auth headers).
        #
        # The SQL connector's ExternalAuthProvider expects a CredentialsProvider
        # with two levels: credentials_provider() -> HeaderFactory, then
        # HeaderFactory() -> Dict[str, str]. Wrap to bridge the interface.
        oauth_provider = oauth_service_principal(config)

        class _CredentialsProvider:
            def auth_type(self):
                return "oauth"

            def __call__(self):
                return oauth_provider

        return _CredentialsProvider()
