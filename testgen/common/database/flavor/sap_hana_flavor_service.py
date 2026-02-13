from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class SapHanaFlavorService(FlavorService):

    varchar_type = "NVARCHAR(1000)"
    default_uppercase = True
    test_query = "SELECT 1 FROM DUMMY"

    def get_connection_string_head(self):
        return f"hana+hdbcli://{self.username}:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        url = f"hana+hdbcli://{self.username}:{quote_plus(self.password)}@{self.host}:{self.port}/"
        if self.dbname:
            url += f"?databaseName={self.dbname}"
        return url

    def get_connect_args(self) -> dict:
        return {}
