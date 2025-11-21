from urllib.parse import quote_plus

from sqlalchemy.engine import URL

from testgen import settings
from testgen.common.database.flavor.flavor_service import FlavorService


class MssqlFlavorService(FlavorService):

    concat_operator = "+"
    escaped_underscore = "[_]"
    use_top = True

    def get_connection_string_head(self):
        return f"mssql+pyodbc://{self.username}:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        connection_url = URL.create(
            "mssql+pyodbc",
            username=self.username,
            password=quote_plus(self.password or ""),
            host=self.host,
            port=int(self.port or 1443),
            database=self.dbname,
            query={
                "driver": "ODBC Driver 18 for SQL Server",
            },
        )

        if self.connect_with_identity:
            connection_url = connection_url._replace(username=None, password=None).update_query_dict({
                "encrypt": "yes",
                "authentication": "ActiveDirectoryMsi",
            })

        if self.sql_flavor_code == "synapse_mssql":
            connection_url = connection_url.update_query_dict({"autocommit": "True"})

        return connection_url.render_as_string(hide_password=False)

    def get_pre_connection_queries(self):
        return [
            ("SET ANSI_DEFAULTS ON;", None),
            ("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;", None),
        ]
    
    def get_connect_args(self):
        connect_args = super().get_connect_args()
        if settings.SKIP_DATABASE_CERTIFICATE_VERIFICATION:
            connect_args["TrustServerCertificate"] = "yes"
        return connect_args
