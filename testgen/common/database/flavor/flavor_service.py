from abc import abstractmethod
from typing import Literal, TypedDict

from testgen.common.encrypt import DecryptText

SQLFlavor = Literal["redshift", "snowflake", "mssql", "postgresql", "databricks"]


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

class FlavorService:

    url = None
    connect_by_url = None
    username = None
    password = None
    host = None
    port = None
    dbname = None
    flavor = None
    dbschema = None
    connect_by_key = None
    private_key = None
    private_key_passphrase = None
    http_path = None
    catalog = None

    def init(self, connection_params: ConnectionParams):
        self.url = connection_params.get("url", None)
        self.connect_by_url = connection_params.get("connect_by_url", False)
        self.username = connection_params.get("project_user")
        self.host = connection_params.get("project_host")
        self.port = connection_params.get("project_port")
        self.dbname = connection_params.get("project_db")
        self.flavor = connection_params.get("sql_flavor")
        self.dbschema = connection_params.get("table_group_schema", None)
        self.connect_by_key = connection_params.get("connect_by_key", False)
        self.http_path = connection_params.get("http_path", None)
        self.catalog = connection_params.get("catalog", None)

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

    def get_concat_operator(self) -> str:
        return "||"

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
