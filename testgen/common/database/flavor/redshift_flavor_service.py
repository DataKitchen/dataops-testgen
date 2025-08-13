from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class RedshiftFlavorService(FlavorService):
    def init(self, connection_params: dict):
        super().init(connection_params)
        # This is for connection purposes. sqlalchemy 1.4.46 uses postgresql to connect to redshift database
        self.flavor = "postgresql"

    def get_connection_string_head(self):
        return f"{self.flavor}://{self.username}:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        # STANDARD FORMAT:  strConnect = 'flavor://username:password@host:port/database'
        return f"{self.flavor}://{self.username}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.dbname}"
