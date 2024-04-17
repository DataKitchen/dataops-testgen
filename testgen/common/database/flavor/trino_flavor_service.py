from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class TrinoFlavorService(FlavorService):
    def get_connection_string_head(self, dctCredentials, strPW):
        strConnect = "{}://{}:{}@".format(
            dctCredentials["flavor"],
            dctCredentials["user"],
            quote_plus(strPW),
        )
        return strConnect

    def get_connection_string_from_fields(self, dctCredentials, strPW):
        # STANDARD FORMAT:  strConnect = 'flavor://username:password@host:port/catalog'
        strConnect = "{}://{}:{}@{}:{}/{}".format(
            dctCredentials["flavor"],
            dctCredentials["user"],
            quote_plus(strPW),
            dctCredentials["host"],
            dctCredentials["port"],
            dctCredentials["catalog"],  # "postgresql"
        )
        return strConnect

    def get_pre_connection_queries(self, dctCredentials):
        return [
            "USE " + dctCredentials["catalog"] + "." + dctCredentials["dbschema"],
        ]

    def get_connect_args(self):
        return {}
