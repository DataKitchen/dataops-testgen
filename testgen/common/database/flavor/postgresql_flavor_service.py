from urllib.parse import quote_plus

from testgen.common.database.column_chars import ColumnChars, ObjectType
from testgen.common.database.flavor.flavor_service import (
    ResolvedConnectionParams,
    base_type_name,
    exact_float_canonical,
)
from testgen.common.database.flavor.redshift_flavor_service import RedshiftFlavorService
from testgen.common.value_hash import DECIMAL_BOUND


class PostgresqlFlavorService(RedshiftFlavorService):

    escaped_underscore = "\\_"
    literal_escapes_backslash = False
    url_scheme = "postgresql"

    # Inherited from Redshift, which has APPROXIMATE PERCENTILE_DISC; PostgreSQL has no equivalent.
    supports_approx_percentile = False

    # Counting these over a text form would split values the engine treats as equal ('1 day' and '24 hours')
    distinct_countable_x_types = frozenset({"bit", "bit varying", "bytea", "interval", "jsonb", "uuid"})

    wide_decimal_type = "NUMERIC(38,0)"

    def canonical_number(self, column_ref: str, is_float: bool) -> str:
        if is_float:
            # A direct cast keeps only 15 significant digits, and a float's shortest text is not its exact value
            canonical = exact_float_canonical(
                column_ref, self.double_type, "NUMERIC", lambda a, b: f"DIV({a}, {b})"
            )
            return f"CAST({canonical} AS {self.varchar_type})"
        # Through NUMERIC, so a money value rounds too
        return super().canonical_number(f"CAST({column_ref} AS NUMERIC)", is_float)

    def hashable_condition(self, column_ref: str, column: ColumnChars) -> str:
        if column.general_type == "N" and not self.is_float(column):
            # Through NUMERIC, since money has no ABS; never a bounded NUMERIC, which cannot hold Infinity.
            # An unconstrained NUMERIC can hold a value that rounds up to the bound.
            return f"{column_ref} IS NOT NULL AND ABS(CAST({column_ref} AS NUMERIC)) < {DECIMAL_BOUND}"
        if column.general_type == "D":
            return f"{super().hashable_condition(column_ref, column)} AND ISFINITE({column_ref})"
        return super().hashable_condition(column_ref, column)

    def hex_to_wide_decimal(self, hex_expr: str) -> str:
        return f"CAST(CAST(CAST('x' || {hex_expr} AS BIT(56)) AS BIGINT) AS {self.wide_decimal_type})"

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        if base_type_name(column.db_data_type).endswith("with time zone"):
            return f"({column_ref} AT TIME ZONE 'UTC')"
        return f"CAST({column_ref} AS TIMESTAMP)"

    def epoch_seconds(self, timestamp_expr: str) -> str:
        return f"FLOOR(EXTRACT(EPOCH FROM {timestamp_expr}))"

    def sampleable_object_types(self, sql_flavor_code: str) -> frozenset[ObjectType] | None:  # noqa: ARG002
        # TABLESAMPLE applies only to tables and materialized views.
        return frozenset({ObjectType.TABLE, ObjectType.MATERIALIZED_VIEW})

    def numeric_value(self, column_ref: str, column_type: str | None) -> str:
        # money compares only with money and has no modulo or cast to float
        if column_type and column_type.lower() == "money":
            return f"{column_ref}::NUMERIC"
        return column_ref

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        if params.host.startswith("/"):
            # Unix socket path — use query-param format for psycopg2
            return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@/{params.dbname}?host={params.host}"
        return super().get_connection_string_from_fields(params)
