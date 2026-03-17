from urllib.parse import quote_plus

from sqlalchemy.engine import URL

from testgen import settings
from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams


class MssqlFlavorService(FlavorService):

    concat_operator = "+"
    escaped_underscore = "[_]"
    row_limiting_clause = "top"
    url_scheme = "mssql+pyodbc"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        connection_url = URL.create(
            self.url_scheme,
            username=params.username,
            password=quote_plus(params.password or ""),
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

        if params.sql_flavor_code == "synapse_mssql":
            connection_url = connection_url.update_query_dict({"autocommit": "True"})

        return connection_url.render_as_string(hide_password=False)

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:  # noqa: ARG002
        return [
            ("SET ANSI_DEFAULTS ON;", None),
            ("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;", None),
        ]

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:
        connect_args = super().get_connect_args(params)
        if settings.SKIP_DATABASE_CERTIFICATE_VERIFICATION:
            connect_args["TrustServerCertificate"] = "yes"
        return connect_args
