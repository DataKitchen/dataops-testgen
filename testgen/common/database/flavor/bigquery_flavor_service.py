from typing import Any

from testgen.common.database.flavor.flavor_service import FlavorService


class BigqueryFlavorService(FlavorService):

    quote_character = "`"
    escaped_single_quote = "\\'"
    varchar_type = "STRING"

    def get_connection_string_head(self):
        return "bigquery://"

    def get_connection_string_from_fields(self):
        return f"bigquery://{self.service_account_key["project_id"] if self.service_account_key else ""}"

    def get_connect_args(self) -> dict:
        return {}

    def get_engine_args(self) -> dict[str,Any]:
        return {"credentials_info": self.service_account_key} if self.service_account_key else {}
