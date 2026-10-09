from urllib.parse import quote_plus

from testgen.common.database.column_chars import ObjectType
from testgen.common.database.flavor.flavor_service import ResolvedConnectionParams
from testgen.common.database.flavor.redshift_flavor_service import RedshiftFlavorService


class PostgresqlFlavorService(RedshiftFlavorService):

    escaped_underscore = "\\_"
    literal_escapes_backslash = False
    url_scheme = "postgresql"

    # Inherited from Redshift, which has APPROXIMATE PERCENTILE_DISC; PostgreSQL has no equivalent.
    supports_approx_percentile = False

    # Counting these over a text form would split values the engine treats as equal ('1 day' and '24 hours')
    distinct_countable_x_types = frozenset({"bit", "bit varying", "bytea", "interval", "jsonb", "uuid"})

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
