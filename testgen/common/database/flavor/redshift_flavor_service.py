from urllib.parse import quote_plus

from sqlalchemy.dialects import registry as _dialect_registry
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2
from sqlalchemy.engine import Engine
from sqlalchemy.engine import create_engine as sqlalchemy_create_engine

from testgen.common.database.flavor.flavor_service import (
    ConnectionParams,
    FlavorService,
    ResolvedConnectionParams,
    resolve_connection_params,
)


class _RedshiftDialect(PGDialect_psycopg2):
    """PostgreSQL dialect patched for Redshift compatibility.

    Redshift doesn't support ``standard_conforming_strings``, which SA 2.0's
    PostgreSQL dialect queries during ``initialize()``. This subclass stubs out
    the check so connections succeed.
    """
    name = "redshift_pg"

    def _set_backslash_escapes(self, connection):
        self._backslash_escapes = False


# Register so ``redshift_pg://`` URLs resolve to this dialect
_dialect_registry.register("redshift_pg", __name__, "_RedshiftDialect")


class RedshiftFlavorService(FlavorService):

    escaped_underscore = "\\\\_"
    url_scheme = "redshift_pg"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@{params.host}:{params.port}/{params.dbname}"
