from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class DatabricksFlavorService(FlavorService):

    def get_connection_string_head(self):
        return f"{self.flavor}://{self.username}:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        return (
            f"{self.flavor}://{self.username}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.dbname}"
            f"?http_path={self.http_path}"
        )
