from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class MssqlFlavorService(FlavorService):
    def get_connection_string_head(self, dctCredentials, strPW):
        username = dctCredentials["user"]
        password = quote_plus(strPW)

        strConnect = f"mssql+pyodbc://{username}:{password}@"

        return strConnect

    def get_connection_string_from_fields(self, dctCredentials, strPW):
        username = dctCredentials["user"]
        password = quote_plus(strPW)
        hostname = dctCredentials["host"]
        port = dctCredentials["port"]
        dbname = dctCredentials["dbname"]

        strConnect = (
            f"mssql+pyodbc://{username}:{password}@{hostname}:{port}/{dbname}?driver=ODBC+Driver+18+for+SQL+Server"
            "&autocommit=True"
        )

        return strConnect

    def get_pre_connection_queries(self, dctCredentials):  # noqa ARG002
        return [
            "SET ANSI_DEFAULTS ON;",
            "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;",
        ]

    def get_concat_operator(self):
        return "+"

    def get_connect_args(self):
        return {}
        # return {"pool_pre_ping": "True"}
