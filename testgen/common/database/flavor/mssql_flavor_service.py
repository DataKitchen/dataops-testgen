from urllib.parse import quote_plus

from testgen import settings
from testgen.common.database.flavor.flavor_service import FlavorService


class MssqlFlavorService(FlavorService):
    def get_connection_string_head(self):
        return f"mssql+pyodbc://{self.username}:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        strConnect = (
            f"mssql+pyodbc://{self.username}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.dbname}?driver=ODBC+Driver+18+for+SQL+Server"
        )

        if "synapse" in self.host:
            strConnect += "&autocommit=True"

        return strConnect

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

    def get_concat_operator(self):
        return "+"
