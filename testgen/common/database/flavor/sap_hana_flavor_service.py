from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams


class SapHanaFlavorService(FlavorService):

    varchar_type = "NVARCHAR(1000)"
    default_uppercase = True
    test_query = "SELECT 1 FROM DUMMY"
    url_scheme = "hana+hdbcli"

    # The catalog records DOUBLE, REAL and SMALLDECIMAL as this type
    exact_sum_excluded_types = frozenset({"numeric"})

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        url = f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@{params.host}:{params.port}/"
        if params.dbname:
            url += f"?databaseName={params.dbname}"
        return url

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:  # noqa: ARG002
        return {}
