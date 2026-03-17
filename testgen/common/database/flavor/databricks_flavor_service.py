from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams


class DatabricksFlavorService(FlavorService):

    quote_character = "`"
    escaped_single_quote = "\\'"
    varchar_type = "STRING"
    url_scheme = "databricks"

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:
        if params.dbname:
            return [(f"USE CATALOG `{params.dbname}`", None)]
        return []

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:
        args = {}
        if params.dbname:
            args["catalog"] = params.dbname
        if params.connect_by_key:
            args["credentials_provider"] = self._get_oauth_credentials_provider(params)
        return args

    def get_connection_string_head(self, params: ResolvedConnectionParams) -> str:
        if params.connect_by_key:
            return f"{self.url_scheme}://oauth:@"
        return f"{self.url_scheme}://token:{quote_plus(params.password)}@"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        if params.connect_by_key:
            return (
                f"{self.url_scheme}://oauth:@{params.host}:{params.port}/{params.dbname}"
                f"?http_path={params.http_path}&catalog={params.dbname}"
            )
        return (
            f"{self.url_scheme}://token:{quote_plus(params.password)}@{params.host}:{params.port}/{params.dbname}"
            f"?http_path={params.http_path}&catalog={params.dbname}"
        )

    def _get_oauth_credentials_provider(self, params: ResolvedConnectionParams):
        from databricks.sdk.core import Config, oauth_service_principal

        config = Config(
            host=f"https://{params.host}",
            client_id=params.username,
            client_secret=params.password,
        )
        # oauth_service_principal(config) returns an OAuthCredentialsProvider,
        # which is callable: provider() -> Dict[str, str] (auth headers).
        #
        # The SQL connector's ExternalAuthProvider expects a CredentialsProvider
        # with two levels: credentials_provider() -> HeaderFactory, then
        # HeaderFactory() -> Dict[str, str]. Wrap to bridge the interface.
        oauth_provider = oauth_service_principal(config)

        class _CredentialsProvider:
            def auth_type(self):
                return "oauth"

            def __call__(self):
                return oauth_provider

        return _CredentialsProvider()
