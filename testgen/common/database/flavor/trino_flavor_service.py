from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams


class TrinoFlavorService(FlavorService):
    url_scheme = "trino"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        # STANDARD FORMAT:  strConnect = 'flavor://username:password@host:port/catalog'
        return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@{params.host}:{params.port}/{params.catalog}"

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:
        return [
            (f"USE {params.catalog}.{params.dbschema}", None),
        ]
