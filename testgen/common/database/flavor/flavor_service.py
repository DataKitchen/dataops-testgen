from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Literal, TypedDict
from urllib.parse import quote_plus

from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine.base import Engine

from testgen.common.encrypt import DecryptText

SQLFlavor = Literal["redshift", "redshift_spectrum", "snowflake", "mssql", "postgresql", "databricks", "bigquery", "oracle", "sap_hana"]
RowLimitingClause = Literal["limit", "top", "fetch"]


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


@dataclass(frozen=True, slots=True)
class ResolvedConnectionParams:
    url: str = ""
    connect_by_url: bool = False
    username: str = ""
    password: str | None = None
    host: str = ""
    port: str = ""
    dbname: str = ""
    dbschema: str | None = None
    sql_flavor: str = ""
    sql_flavor_code: str = ""
    connect_by_key: bool = False
    private_key: str | None = None
    private_key_passphrase: str | None = None
    http_path: str = ""
    catalog: str = ""
    warehouse: str = ""
    service_account_key: dict[str, Any] | None = None
    connect_with_identity: bool = False


def _decrypt_if_needed(value: Any) -> str | None:
    if isinstance(value, memoryview | bytes):
        return DecryptText(value)
    return value


def resolve_connection_params(connection_params: ConnectionParams) -> ResolvedConnectionParams:
    sql_flavor = connection_params.get("sql_flavor") or ""
    return ResolvedConnectionParams(
        url=connection_params.get("url") or "",
        connect_by_url=connection_params.get("connect_by_url", False),
        username=connection_params.get("project_user") or "",
        password=_decrypt_if_needed(connection_params.get("project_pw_encrypted")),
        host=connection_params.get("project_host") or "",
        port=connection_params.get("project_port") or "",
        dbname=connection_params.get("project_db") or "",
        dbschema=connection_params.get("table_group_schema"),
        sql_flavor=sql_flavor,
        sql_flavor_code=connection_params.get("sql_flavor_code") or sql_flavor,
        connect_by_key=connection_params.get("connect_by_key", False),
        private_key=_decrypt_if_needed(connection_params.get("private_key")),
        private_key_passphrase=_decrypt_if_needed(connection_params.get("private_key_passphrase")),
        http_path=connection_params.get("http_path") or "",
        catalog=connection_params.get("catalog") or "",
        warehouse=connection_params.get("warehouse") or "",
        service_account_key=connection_params.get("service_account_key"),
        connect_with_identity=connection_params.get("connect_with_identity") or False,
    )


class FlavorService:

    concat_operator = "||"
    quote_character = '"'
    escaped_single_quote = "''"
    escaped_underscore = "\\_"
    escape_clause = ""
    varchar_type = "VARCHAR(1000)"
    ddf_table_ref = "table_name"
    row_limiting_clause: RowLimitingClause = "limit"
    default_uppercase = False
    test_query = "SELECT 1"
    url_scheme = "postgresql"

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:  # noqa: ARG002
        return []

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:  # noqa: ARG002
        return {"connect_timeout": 3600}

    def get_engine_args(self, params: ResolvedConnectionParams) -> dict[str, Any]:  # noqa: ARG002
        return {}

    def create_engine(self, connection_params: ConnectionParams) -> Engine:
        params = resolve_connection_params(connection_params)
        return sqlalchemy_create_engine(
            self.get_connection_string(params),
            connect_args=self.get_connect_args(params),
            **self.get_engine_args(params),
        )

    def get_connection_string(self, params: ResolvedConnectionParams) -> str:
        if params.connect_by_url:
            header = self.get_connection_string_head(params)
            return header + params.url
        else:
            return self.get_connection_string_from_fields(params)

    @abstractmethod
    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        raise NotImplementedError("Subclasses must implement this method")

    def get_connection_string_head(self, params: ResolvedConnectionParams) -> str:
        return f"{self.url_scheme}://{params.username}:{quote_plus(params.password)}@"

