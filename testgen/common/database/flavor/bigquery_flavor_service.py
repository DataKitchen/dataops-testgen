from typing import Any

from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams, base_type_name
from testgen.common.value_hash import DECIMAL_BOUND


class BigqueryFlavorService(FlavorService):

    quote_character = "`"
    escaped_single_quote = "\\'"
    literal_escapes_backslash = True
    varchar_type = "STRING"
    url_scheme = "bigquery"

    # A managed, versionless engine: no instance can lack APPROX_QUANTILES, so nothing to probe.
    supports_approx_percentile = True

    supports_value_hash = True
    float_types = frozenset({"float64"})
    wide_decimal_type = "BIGNUMERIC"

    def canonical_number(self, column_ref: str, is_float: bool) -> str:
        # ROUND of an INT64 returns a FLOAT64, so the value is widened first
        exact = f"CAST({column_ref} AS BIGNUMERIC)"
        if is_float:
            exact = f"ROUND({exact}, 9)"
        return f"CAST(ROUND({exact}, 6) * 1000000 AS STRING)"

    def hashable_condition(self, column_ref: str, column: ColumnChars) -> str:
        if column.general_type == "N" and not self.is_float(column):
            # BigQuery has no integer literal as wide as the bound, and a BIGNUMERIC can hold a value that
            # rounds up to it
            return f"{column_ref} IS NOT NULL AND ABS(CAST({column_ref} AS BIGNUMERIC)) < BIGNUMERIC '{DECIMAL_BOUND}'"
        return super().hashable_condition(column_ref, column)

    def md5_hex(self, text_expr: str) -> str:
        return f"TO_HEX(MD5({text_expr}))"

    def hex_to_wide_decimal(self, hex_expr: str) -> str:
        return f"CAST(CAST(CONCAT('0x', {hex_expr}) AS INT64) AS BIGNUMERIC)"

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        # A TIMESTAMP is an instant; a DATETIME is a wall-clock time
        if base_type_name(column.db_data_type) == "timestamp":
            return f"DATETIME({column_ref}, 'UTC')"
        return f"DATETIME({column_ref})"

    def format_timestamp(self, timestamp_expr: str) -> str:
        return f"FORMAT_DATETIME('%Y-%m-%d %H:%M:%S', {timestamp_expr})"

    def epoch_seconds(self, timestamp_expr: str) -> str:
        return f"DATETIME_DIFF(DATETIME_TRUNC({timestamp_expr}, SECOND), DATETIME '1970-01-01 00:00:00', SECOND)"

    def get_connection_string_head(self, params: ResolvedConnectionParams) -> str:  # noqa: ARG002
        return f"{self.url_scheme}://"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        project_id = params.service_account_key["project_id"] if params.service_account_key else ""
        return f"{self.url_scheme}://{project_id}"

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:  # noqa: ARG002
        return {}

    def get_engine_args(self, params: ResolvedConnectionParams) -> dict[str, Any]:
        return {"credentials_info": params.service_account_key} if params.service_account_key else {}
