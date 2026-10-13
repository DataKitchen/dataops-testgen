import re
from urllib.parse import quote_plus

from sqlalchemy.dialects import registry as _dialect_registry
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2

from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.flavor_service import (
    FlavorService,
    ResolvedConnectionParams,
    base_type_name,
    exact_float_canonical,
)


class _RedshiftDialect(PGDialect_psycopg2):
    """PostgreSQL dialect patched for Redshift compatibility.

    Redshift doesn't support ``standard_conforming_strings``, which SA 2.0's
    PostgreSQL dialect queries during ``initialize()``. This subclass stubs out
    the check so connections succeed.
    """
    name = "redshift_pg"
    supports_statement_cache = True

    def _set_backslash_escapes(self, _connection):
        self._backslash_escapes = False


# Register so ``redshift_pg://`` URLs resolve to this dialect
_dialect_registry.register("redshift_pg", __name__, "_RedshiftDialect")


class RedshiftFlavorService(FlavorService):

    escaped_underscore = "\\\\_"
    literal_escapes_backslash = True
    url_scheme = "redshift_pg"

    # APPROXIMATE PERCENTILE_DISC runs only on a query that references a user table, so it cannot
    # be probed on a derived row; every supported Redshift release has it.
    supports_approx_percentile = True

    distinct_countable_x_types = frozenset({"binary varying", "varbyte"})

    supports_value_hash = True
    float_types = frozenset({"double precision", "real", "double", "float", "float4", "float8"})

    def text_value(self, column_ref: str, column_type: str | None) -> str:
        # CHAR values are stored padded with spaces to the declared length.
        if column_type and re.fullmatch(r"char(\(\d+\))?", column_type.lower()):
            return f"RTRIM({column_ref})"
        return column_ref

    def canonical_number(self, column_ref: str, is_float: bool) -> str:
        if is_float:
            # A direct cast is inexact for a large double. The quotient is cast back to a whole number:
            # NUMERIC division widens the scale, which leaves too few whole digits for the scaled value.
            canonical = exact_float_canonical(
                column_ref,
                self.double_type,
                "NUMERIC(38,0)",
                lambda a, b: f"CAST((({a}) - MOD({a}, {b})) / {b} AS NUMERIC(38,0))",
            )
            return f"CAST(CAST({canonical} AS NUMERIC(38,0)) AS {self.varchar_type})"
        return super().canonical_number(column_ref, is_float)

    def hex_to_wide_decimal(self, hex_expr: str) -> str:
        return f"CAST(STRTOL({hex_expr}, 16) AS {self.wide_decimal_type})"

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        if base_type_name(column.db_data_type).endswith("with time zone"):
            return f"CONVERT_TIMEZONE('UTC', {column_ref})"
        return f"CAST({column_ref} AS TIMESTAMP)"

    def format_timestamp(self, timestamp_expr: str) -> str:
        return f"TO_CHAR({timestamp_expr}, 'YYYY-MM-DD HH24:MI:SS')"

    def epoch_seconds(self, timestamp_expr: str) -> str:
        return f"DATEDIFF(second, CAST('1970-01-01' AS TIMESTAMP), {timestamp_expr})"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@{params.host}:{params.port}/{params.dbname}"
