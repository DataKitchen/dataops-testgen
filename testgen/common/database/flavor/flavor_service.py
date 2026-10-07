from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict
from urllib.parse import quote_plus

from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine.base import Connection, Engine

from testgen.common.database.column_chars import ColumnChars, ObjectType
from testgen.common.database.file_declarations import FileDeclaration
from testgen.common.encrypt import DecryptText

SQLFlavor = Literal["redshift", "redshift_spectrum", "snowflake", "mssql", "postgresql", "databricks", "duckdb", "bigquery", "oracle", "sap_hana", "salesforce_data360"]
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
    connect_with_service_principal: bool
    sql_flavor_code: str
    parameters: dict[str, Any]
    secrets: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ConnectionField:
    """One entry in a flavor's ``parameters`` or ``secrets`` shape."""

    key: str
    label: str
    required: bool = False


def _validate_declared_fields(
    schema: tuple[ConnectionField, ...], supplied: dict[str, Any] | None, noun: str
) -> None:
    """Raise ``ValueError`` naming the offending field if ``supplied`` does not match ``schema``."""
    declared = {entry.key: entry for entry in schema}
    values = supplied or {}

    for key in values:
        if key not in declared:
            raise ValueError(f"'{key}' is not a connection {noun} for this connection type.")

    for entry in schema:
        if entry.required:
            value = values.get(entry.key)
            if value is None or (isinstance(value, str) and not value.strip()):
                raise ValueError(f"{entry.label} is required.")


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
    connect_with_service_principal: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, Any] = field(default_factory=dict)


def _decrypt_if_needed(value: Any) -> str | None:
    if isinstance(value, memoryview | bytes):
        return DecryptText(value)
    return value


def resolve_connection_params(connection_params: ConnectionParams) -> ResolvedConnectionParams:
    sql_flavor = connection_params.get("sql_flavor") or ""
    host = connection_params.get("project_host") or ""
    port = connection_params.get("project_port") or ""
    # Lazy import to keep the flavor layer free of standalone concerns at module load.
    from testgen.common.standalone_postgres import EMBEDDED_HOST_SENTINEL, get_target_host_port, is_standalone_mode
    if host == EMBEDDED_HOST_SENTINEL and is_standalone_mode():
        host, live_port = get_target_host_port()
        port = live_port or ""
    return ResolvedConnectionParams(
        url=connection_params.get("url") or "",
        connect_by_url=connection_params.get("connect_by_url", False),
        username=connection_params.get("project_user") or "",
        password=_decrypt_if_needed(connection_params.get("project_pw_encrypted")),
        host=host,
        port=port,
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
        connect_with_service_principal=connection_params.get("connect_with_service_principal") or False,
        parameters=connection_params.get("parameters") or {},
        secrets=connection_params.get("secrets") or {},
    )


class FlavorConnectionError(Exception):
    """A connection failure whose message is written for the user rather than the log.

    ``test_connection_status`` shows it verbatim, so the text has to stand on its own.
    """


class FlavorService:

    concat_operator = "||"
    quote_character = '"'
    escaped_single_quote = "''"
    literal_escapes_backslash = False
    string_literal_prefix = ""
    escaped_underscore = "\\_"
    escape_clause = ""
    varchar_type = "VARCHAR(1000)"
    ddf_table_ref = "table_name"
    row_limiting_clause: RowLimitingClause = "limit"

    def row_limit_clauses(self, n: int) -> tuple[str, str]:
        """Return ``(prefix, suffix)`` SQL fragments for limiting a SELECT to ``n`` rows."""
        if self.row_limiting_clause == "top":
            return f"TOP {n}", ""
        if self.row_limiting_clause == "fetch":
            return "", f"FETCH FIRST {n} ROWS ONLY"
        return "", f"LIMIT {n}"

    default_uppercase = False
    test_query = "SELECT 1"
    url_scheme = "postgresql"

    metadata_via_api = False

    # Whether the engine has an approximate percentile function profiling can use in place of
    # an exact PERCENTILE_CONT. A flavor whose function is version-gated also gives a probe query,
    # so the capability is confirmed against the target rather than assumed from the declaration.
    supports_approx_percentile = False
    approx_percentile_probe: str | None = None

    def qualifies_table_refs_with_schema(self, sql_flavor_code: str) -> bool:  # noqa: ARG002
        """Whether generated SQL names a table as ``schema.table`` rather than ``table``.

        Takes the code rather than the family because two codes sharing one engine can reach
        their tables differently.
        """
        return True

    def sampleable_object_types(self, sql_flavor_code: str) -> frozenset[ObjectType] | None:  # noqa: ARG002
        """Object types that can be sampled with TABLESAMPLE.

        ``None`` = sample regardless of type; a non-empty frozenset =
        restrict to those types; an empty frozenset = disable sampling.
        """
        return None

    def table_hint(self, sql_flavor_code: str) -> str:  # noqa: ARG002
        """SQL fragment appended after a table reference to control read
        locking. Empty when the flavor doesn't use hints.
        """
        return ""

    def text_value(self, column_ref: str, column_type: str | None) -> str:  # noqa: ARG002
        """Return the SQL expression that reads a column's text value.

        Args:
            column_ref: The quoted column reference.
            column_type: The column's type as recorded in the data catalog.

        Returns:
            ``column_ref``, or an expression over it that strips padding the flavor adds to
            fixed-length text values.
        """
        return column_ref

    def get_schema_columns(self, _params: ResolvedConnectionParams, _schema: str) -> list[ColumnChars] | None:
        """Return column metadata without querying information_schema.

        Override this for flavors that lack information_schema and set ``metadata_via_api = True``.
        Return None to use the standard SQL template path.
        """
        return None

    def string_literal(self, value: str) -> str:
        """Return ``value`` as a single-quoted SQL string literal."""
        if self.literal_escapes_backslash:
            value = value.replace("\\", "\\\\")
        escaped = value.replace("'", self.escaped_single_quote)
        return f"{self.string_literal_prefix}'{escaped}'"

    def string_literal_or_null(self, value: str | None) -> str:
        """Return ``value`` as a SQL string literal, or ``NULL`` when it is empty."""
        return self.string_literal(value) if value else "NULL"

    def string_literal_list(self, values: list[str]) -> str:
        """Return ``values`` as a comma-separated list of SQL string literals, or ``NULL`` when empty."""
        return ", ".join(self.string_literal(value) for value in values) or "NULL"

    def get_table_ref(self, schema: str, table: str, sql_flavor_code: str) -> str:
        """Return a table reference for SQL queries, qualified where the flavor qualifies."""
        q = self.quote_character
        if not self.qualifies_table_refs_with_schema(sql_flavor_code):
            return f"{q}{table}{q}"
        return f"{q}{schema}{q}.{q}{table}{q}"

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:  # noqa: ARG002
        return []

    def parameters_schema(self, sql_flavor_code: str) -> tuple[ConnectionField, ...]:  # noqa: ARG002
        """Shape of the flavor's ``connections.parameters`` entry. Empty means the flavor stores none."""
        return ()

    def secrets_schema(self, sql_flavor_code: str) -> tuple[ConnectionField, ...]:  # noqa: ARG002
        """Shape of the flavor's ``connections.secrets`` entry. Empty means the flavor stores none."""
        return ()

    def validate_settings(
        self, parameters: dict[str, Any] | None, secrets: dict[str, Any] | None, sql_flavor_code: str
    ) -> None:
        """Raise ``ValueError`` naming the first field ``parameters`` or ``secrets`` gets wrong.

        Checks each against the shape the flavor declares for it.
        """
        _validate_declared_fields(self.parameters_schema(sql_flavor_code), parameters, "parameter")
        _validate_declared_fields(self.secrets_schema(sql_flavor_code), secrets, "secret")

    def scrub_settings(
        self,
        parameters: dict[str, Any] | None,
        secrets: dict[str, Any] | None,
        sql_flavor_code: str,  # noqa: ARG002
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The ``parameters`` and ``secrets`` with every value the connection's auth mode does not read removed."""
        return parameters, secrets

    def test_connection_details(
        self,
        connection: Connection,  # noqa: ARG002
        params: ResolvedConnectionParams,  # noqa: ARG002
    ) -> str | None:
        """Text shown beneath a successful connection test, or None when there is nothing to add.

        ``connection`` is the connection that was just tested, still open.
        """
        return None

    def init(
        self,
        connection: Connection,
        params: ResolvedConnectionParams,
        declarations: list[FileDeclaration],
    ) -> None:
        """Prepare a physical connection for use.

        Runs after the pre-connection queries, once per DBAPI connection rather than once per
        checkout, so it is the place for setup that belongs to the database instead of to the
        session. Unlike the pre-connection queries, a failure here aborts the connection instead
        of being logged and skipped, so it is also the place for setup the flavor cannot operate
        without.

        ``declarations`` are the table group's file declarations, empty when the connection is
        opened without a table group.
        """

    def declaration_failures(self, connection: Connection) -> dict[str, str]:  # noqa: ARG002
        """Name and reason for each file declaration ``init`` could not make queryable."""
        return {}

    def file_count_queries(
        self,
        params: ResolvedConnectionParams,  # noqa: ARG002
        declarations: list[FileDeclaration],  # noqa: ARG002
    ) -> list[str]:
        """One query per readable file declaration, each returning ``table_name`` and ``file_ct``.

        Empty for a flavor whose tables are not declared as files.
        """
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
