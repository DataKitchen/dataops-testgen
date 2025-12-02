from abc import abstractmethod
from typing import Any, Literal, TypedDict
from urllib.parse import parse_qs, urlparse

from testgen.common.encrypt import DecryptText

SQLFlavor = Literal["redshift", "redshift_spectrum", "snowflake", "mssql", "postgresql", "databricks"]


class ConnectionParams(TypedDict):
    sql_flavor: SQLFlavor
    project_host: str
    project_port: str
    project_user: str
    project_db: str
    table_group_schema: str
    project_pw_encrypted: bytes
    url: str
    connect_by_url: bool
    connect_by_key: bool
    private_key: bytes
    private_key_passphrase: bytes
    http_path: str
    service_account_key: dict[str,Any]
    connect_with_identity: bool
    sql_flavor_code: str

class FlavorService:

    concat_operator = "||"
    quote_character = '"'
    escaped_single_quote = "''"
    escaped_underscore = "\\_"
    escape_clause = ""
    varchar_type = "VARCHAR(1000)"
    ddf_table_ref = "table_name"
    use_top = False
    default_uppercase = False

    def init(self, connection_params: ConnectionParams):
        self.url = connection_params.get("url") or ""
        self.connect_by_url = connection_params.get("connect_by_url", False)
        self.username = connection_params.get("project_user") or ""
        self.host = connection_params.get("project_host") or ""
        self.port = connection_params.get("project_port") or ""
        self.dbname = connection_params.get("project_db") or ""
        self.flavor = connection_params.get("sql_flavor")
        self.dbschema = connection_params.get("table_group_schema", None)
        self.connect_by_key = connection_params.get("connect_by_key", False)
        self.http_path = connection_params.get("http_path") or ""
        self.catalog = connection_params.get("catalog") or ""
        self.warehouse = connection_params.get("warehouse") or ""
        self.service_account_key = connection_params.get("service_account_key", None)
        self.connect_with_identity = connection_params.get("connect_with_identity") or False
        self.sql_flavor_code = connection_params.get("sql_flavor_code") or self.flavor

        password = connection_params.get("project_pw_encrypted", None)
        if isinstance(password, memoryview) or isinstance(password, bytes):
            password = DecryptText(password)
        self.password = password

        private_key = connection_params.get("private_key", None)
        if isinstance(private_key, memoryview) or isinstance(private_key, bytes):
            private_key = DecryptText(private_key)
        self.private_key = private_key

        private_key_passphrase = connection_params.get("private_key_passphrase", None)
        if isinstance(private_key_passphrase, memoryview) or isinstance(private_key_passphrase, bytes):
            private_key_passphrase = DecryptText(private_key_passphrase)
        self.private_key_passphrase = private_key_passphrase

    def get_pre_connection_queries(self) -> list[tuple[str, dict | None]]:
        return []

    def get_connect_args(self) -> dict:
        return {"connect_timeout": 3600}

    def get_engine_args(self) -> dict[str,Any]:
        return {}

    def get_connection_string(self) -> str:
        if self.connect_by_url:
            header = self.get_connection_string_head()
            url = header + self.url
            return url
        else:
            return self.get_connection_string_from_fields()

    @abstractmethod
    def get_connection_string_from_fields(self) -> str:
        raise NotImplementedError("Subclasses must implement this method")

    @abstractmethod
    def get_connection_string_head(self) -> str:
        raise NotImplementedError("Subclasses must implement this method")

    def get_parts_from_connection_string(self) -> dict[str, Any]:
        if self.connect_by_url:
            if not self.url:
                return {}

            parsed_url = urlparse(self.get_connection_string())
            credentials, location = (
                parsed_url.netloc if "@" in parsed_url.netloc else f"@{parsed_url.netloc}"
            ).split("@")
            username, password = (
                credentials if ":" in credentials else f"{credentials}:"
            ).split(":")
            host, port = (
                location if ":" in location else f"{location}:"
            ).split(":")

            database = (path_patrs[0] if (path_patrs := parsed_url.path.strip("/").split("/")) else "")

            extras = {
                param_name: param_values[0]
                for param_name, param_values in parse_qs(parsed_url.query or "").items()
            }

            return {
                "username": username,
                "password": password,
                "host": host,
                "port": port,
                "dbname": database,
                **extras,
            }

        return {
            "username": self.username,
            "password": self.password,
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "http_path": self.http_path,
            "catalog": self.catalog,
        }
