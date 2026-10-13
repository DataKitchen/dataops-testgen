import sys
from urllib.parse import quote_plus

import oracledb

from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.flavor_service import (
    FlavorService,
    ResolvedConnectionParams,
    base_type_name,
    exact_float_canonical,
)
from testgen.common.value_hash import DECIMAL_BOUND

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

    # APPROX_PERCENTILE is version-gated (12c Release 2), so the probe decides; older instances stay exact.
    supports_approx_percentile = True
    approx_percentile_probe = "SELECT APPROX_PERCENTILE(0.5) WITHIN GROUP (ORDER BY n) FROM (SELECT 1 n FROM dual) t"

    supports_value_hash = True
    float_types = frozenset({"float", "binary_float", "binary_double"})
    double_type = "BINARY_DOUBLE"
    wide_decimal_type = "NUMBER(38,0)"

    def canonical_text(self, column_ref: str, column: ColumnChars) -> str:
        text = super().canonical_text(column_ref, column)
        # STANDARD_HASH hashes a national-character value in the national character set, not UTF-8
        if base_type_name(column.db_data_type) in ("nchar", "nvarchar2"):
            return f"TO_CHAR({text})"
        return text

    def canonical_number(self, column_ref: str, is_float: bool) -> str:
        if is_float:
            # A direct cast keeps only 17 significant digits
            canonical = exact_float_canonical(
                column_ref,
                self.double_type,
                self.wide_decimal_type,
                lambda a, b: f"(({a}) - MOD({a}, {b})) / {b}",
                bigint_type="NUMBER(19,0)",
            )
            return f"CAST({canonical} AS {self.varchar_type})"
        return super().canonical_number(column_ref, is_float)

    def hashable_condition(self, column_ref: str, column: ColumnChars) -> str:
        if column.general_type == "N" and not self.is_float(column):
            # Compared directly: an unconstrained NUMBER can exceed the wide decimal, or hold a value that
            # rounds up to the bound, and NUMBER comparison is exact
            return (
                f"{column_ref} IS NOT NULL AND {column_ref} < {DECIMAL_BOUND} AND {column_ref} > -{DECIMAL_BOUND}"
            )
        return super().hashable_condition(column_ref, column)

    def md5_hex(self, text_expr: str) -> str:
        return f"LOWER(RAWTOHEX(STANDARD_HASH({text_expr}, 'MD5')))"

    def hash_integer(self, text_expr: str) -> str:
        return self.hex_to_wide_decimal(f"SUBSTR({self.md5_hex(text_expr)}, 1, 14)")

    def hex_to_wide_decimal(self, hex_expr: str) -> str:
        return f"TO_NUMBER(UPPER({hex_expr}), 'XXXXXXXXXXXXXX')"

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        if base_type_name(column.db_data_type).endswith("time zone"):
            return f"CAST(SYS_EXTRACT_UTC({column_ref}) AS TIMESTAMP)"
        return f"CAST({column_ref} AS TIMESTAMP)"

    def format_timestamp(self, timestamp_expr: str) -> str:
        return f"TO_CHAR({timestamp_expr}, 'YYYY-MM-DD HH24:MI:SS')"

    def epoch_seconds(self, timestamp_expr: str) -> str:
        # Whole minutes from date arithmetic, which counts in fractional days, then the seconds field
        return (
            f"(ROUND((TRUNC({timestamp_expr}, 'MI') - DATE '1970-01-01') * 1440) * 60"
            f" + FLOOR(EXTRACT(SECOND FROM {timestamp_expr})))"
        )

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@{params.host}:{params.port}?service_name={params.dbname}"

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:  # noqa: ARG002
        return [
            ("ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS'", None),
        ]

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:  # noqa: ARG002
        return {}
