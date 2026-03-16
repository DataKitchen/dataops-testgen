from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams


class RedshiftFlavorService(FlavorService):

    escaped_underscore = "\\\\_"
    url_scheme = "postgresql"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        # STANDARD FORMAT:  strConnect = 'flavor://username:password@host:port/database'
        return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@{params.host}:{params.port}/{params.dbname}"
