from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class MssqlFlavorService(FlavorService):
    def get_connection_string_head(self, strPW):
        username = self.username
        password = quote_plus(strPW)

        strConnect = f"mssql+pyodbc://{username}:{password}@"

        return strConnect

    def get_connection_string_from_fields(self, strPW, is_password_overwritten: bool = False):    # NOQA ARG002
        password = quote_plus(strPW)

        strConnect = (
            f"mssql+pyodbc://{self.username}:{password}@{self.host}:{self.port}/{self.dbname}?driver=ODBC+Driver+18+for+SQL+Server"
        )

        if "synapse" in self.host:
            strConnect += "&autocommit=True"

        return strConnect

    def get_pre_connection_queries(self):  # ARG002
        return [
            "SET ANSI_DEFAULTS ON;",
            "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;",
        ]

    def get_concat_operator(self):
        return "+"
