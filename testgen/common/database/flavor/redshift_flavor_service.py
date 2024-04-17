from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class RedshiftFlavorService(FlavorService):
    def get_connection_string_head(self, dctCredentials, strPW):
        strConnect = "{}://{}:{}@".format(
            dctCredentials["flavor"],
            dctCredentials["user"],
            quote_plus(strPW),
        )
        return strConnect

    def get_connection_string_from_fields(self, dctCredentials, strPW):
        # STANDARD FORMAT:  strConnect = 'flavor://username:password@host:port/database'
        strConnect = "{}://{}:{}@{}:{}/{}".format(
            dctCredentials["flavor"],
            dctCredentials["user"],
            quote_plus(strPW),
            dctCredentials["host"],
            dctCredentials["port"],
            dctCredentials["dbname"],
        )
        return strConnect

    def get_pre_connection_queries(self, dctCredentials):
        return [
            "SET SEARCH_PATH = '" + dctCredentials["dbschema"] + "'",
        ]

    def get_connect_args(self):
        return {}
