from sqlalchemy.engine import URL

from testgen import settings
from testgen.common.database.column_chars import ObjectType
from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams


class MssqlFlavorService(FlavorService):

    concat_operator = "+"
    escaped_underscore = "[_]"
    row_limiting_clause = "top"
    url_scheme = "mssql+pyodbc"
    # TABLESAMPLE is rejected on views; SQL Server has no materialized views, so only base tables.
    sampleable_object_types = frozenset({ObjectType.TABLE})

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        connection_url = URL.create(
            self.url_scheme,
            username=params.username,
            password=params.password or "",
            host=params.host,
            port=int(params.port or 1443),
            database=params.dbname,
            query={
                "driver": "ODBC Driver 18 for SQL Server",
            },
        )

        if params.connect_with_identity:
            connection_url = connection_url._replace(username=None, password=None).update_query_dict({
                "encrypt": "yes",
                "authentication": "ActiveDirectoryMsi",
            })

        return connection_url.render_as_string(hide_password=False)

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:
        # Synapse dedicated SQL pool rejects these SET commands: ANSI_DEFAULTS isn't
        # implemented, ANSI_WARNINGS can't be turned off, and only READ UNCOMMITTED
        # isolation is allowed (and is the default). Each one would log a warning.
        if params.sql_flavor_code == "synapse_mssql":
            return []

        # ANSI_DEFAULTS turns on ANSI_NULLS / ANSI_PADDING / QUOTED_IDENTIFIER (good)
        # *and* ANSI_WARNINGS (bad here). pyodbc>=5.2 escalates SQL Server's 01003
        # "Null value is eliminated by an aggregate" warning into a pyodbc.Error,
        # which breaks profiling/CAT queries that aggregate over nullable columns.
        # Target connections are read-only, so disabling ANSI_WARNINGS is safe.
        return [
            ("SET ANSI_DEFAULTS ON;", None),
            ("SET ANSI_WARNINGS OFF;", None),
            ("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;", None),
        ]

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:
        # Imported here rather than at module scope: pyodbc requires the unixODBC native
        # library (libodbc), which is absent in some environments that import this module
        # (e.g. the unit-test image) but always present where a SQL Server connection is
        # actually made — which is the only path that reaches this method.
        import pyodbc

        # Let SQLAlchemy's pool be the sole owner of connection lifecycle. pyodbc enables
        # ODBC-driver-manager pooling by default, so a connection SQLAlchemy discards can be
        # retained by the ODBC pool and left sleeping on the server with its transaction
        # state unreset until the next checkout. Setting this during engine creation is
        # before the first connection, which is when it must be set.
        pyodbc.pooling = False

        # pyodbc defaults to autocommit=False, which opens an implicit transaction on the
        # first statement (including the pre-connection SET queries) and holds it until
        # commit/rollback/close. TestGen only reads from target databases, so there is no
        # multi-statement transaction to preserve, and running in autocommit keeps a
        # connection from sitting idle on the server holding an open transaction. This must
        # be set at connect time: SQLAlchemy 2.x raises if the isolation level is changed
        # after a statement has autobegun a transaction.
        connect_args = super().get_connect_args(params)
        connect_args["autocommit"] = True
        if settings.SKIP_DATABASE_CERTIFICATE_VERIFICATION:
            connect_args["TrustServerCertificate"] = "yes"
        return connect_args
