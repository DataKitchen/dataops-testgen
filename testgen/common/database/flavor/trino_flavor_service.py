from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class TrinoFlavorService(FlavorService):
    def get_connection_string_head(self):
        return f"{self.flavor}://{self.username}:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        # STANDARD FORMAT:  strConnect = 'flavor://username:password@host:port/catalog'
        return f"{self.flavor}://{self.username}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.catalog}"

    def get_pre_connection_queries(self):
        return [
            (f"USE {self.catalog}.{self.dbschema}", None),
        ]
