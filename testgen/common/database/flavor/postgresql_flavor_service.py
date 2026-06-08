from urllib.parse import quote_plus

from testgen.common.database.column_chars import ObjectType
from testgen.common.database.flavor.flavor_service import ResolvedConnectionParams
from testgen.common.database.flavor.redshift_flavor_service import RedshiftFlavorService


class PostgresqlFlavorService(RedshiftFlavorService):

    escaped_underscore = "\\_"
    url_scheme = "postgresql"
    # TABLESAMPLE applies only to tables and materialized views
    sampleable_object_types = frozenset({ObjectType.TABLE, ObjectType.MATERIALIZED_VIEW})

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        if params.host.startswith("/"):
            # Unix socket path — use query-param format for psycopg2
            return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@/{params.dbname}?host={params.host}"
        return super().get_connection_string_from_fields(params)
