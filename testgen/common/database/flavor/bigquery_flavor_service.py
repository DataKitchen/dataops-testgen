from typing import Any

from testgen.common.database.flavor.flavor_service import FlavorService, ResolvedConnectionParams


class BigqueryFlavorService(FlavorService):

    quote_character = "`"
    escaped_single_quote = "\\'"
    varchar_type = "STRING"
    url_scheme = "bigquery"

    def get_connection_string_head(self, params: ResolvedConnectionParams) -> str:  # noqa: ARG002
        return f"{self.url_scheme}://"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        project_id = params.service_account_key["project_id"] if params.service_account_key else ""
        return f"{self.url_scheme}://{project_id}"

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:  # noqa: ARG002
        return {}

    def get_engine_args(self, params: ResolvedConnectionParams) -> dict[str, Any]:
        return {"credentials_info": params.service_account_key} if params.service_account_key else {}
