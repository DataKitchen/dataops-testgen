from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class TrinoFlavorService(FlavorService):
    def get_connection_string_head(self, strPW):
        strConnect = f"{self.flavor}://{self.username}:{quote_plus(strPW)}@"
        return strConnect

    def get_connection_string_from_fields(self, strPW, is_password_overwritten: bool = False):  # NOQA ARG002
        # STANDARD FORMAT:  strConnect = 'flavor://username:password@host:port/catalog'
        return f"{self.flavor}://{self.username}:{quote_plus(strPW)}@{self.host}:{self.port}/{self.catalog}"

    def get_pre_connection_queries(self):
        return [
            "USE " + self.catalog + "." + self.dbschema,
        ]
