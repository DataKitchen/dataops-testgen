from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class DatabricksFlavorService(FlavorService):

    quote_character = "`"
    escaped_single_quote = "\\'"
    varchar_type = "STRING"

    def get_pre_connection_queries(self) -> list[tuple[str, dict | None]]:
        if self.dbname:
            return [(f"USE CATALOG `{self.dbname}`", None)]
        return []

    def get_connect_args(self) -> dict:
        args = {}
        if self.dbname:
            args["catalog"] = self.dbname
        if self.connect_by_key:
            args["credentials_provider"] = self._get_oauth_credentials_provider()
        return args

    def get_connection_string_head(self):
        if self.connect_by_key:
            return f"{self.flavor}://oauth:@"
        return f"{self.flavor}://token:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        if self.connect_by_key:
            return (
                f"{self.flavor}://oauth:@{self.host}:{self.port}/{self.dbname}"
                f"?http_path={self.http_path}&catalog={self.dbname}"
            )
        return (
            f"{self.flavor}://token:{quote_plus(self.password)}@{self.host}:{self.port}/{self.dbname}"
            f"?http_path={self.http_path}&catalog={self.dbname}"
        )

    def _get_oauth_credentials_provider(self):
        from databricks.sdk.core import Config, oauth_service_principal

        config = Config(
            host=f"https://{self.host}",
            client_id=self.username,
            client_secret=self.password,
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
