"""Per-flavor connection shape — which auth modes a database flavor offers, which
fields each mode needs, and how those fields map onto the (often leaky)
``Connection`` columns.

The ``connections`` table is one flat structure shared by every flavor, so the
same physical column carries different data depending on the flavor:
``project_db`` is the database on PostgreSQL, the service name on Oracle, the
catalog on Databricks and the username on Salesforce. This module is where that
mapping lives, so a surface rendering a connection can label each value the way
the target database names it.

Field labels are the human labels the per-flavor JS forms in
``ui/static/js/components/connection_form.js`` give each field.

``ConnField.secret`` marks the four encrypted columns. Every consumer filters on
it rather than maintaining its own denylist, so a credential cannot reach a
response by being forgotten.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum

from testgen.common.flavors import FLAVOR_CODE_TO_LABEL
from testgen.common.models.connection import Connection


class ConnectionMode(StrEnum):
    PASSWORD = "Password"  # noqa: S105 — auth-mode label, not a credential
    KEY_PAIR = "Key-Pair"
    MANAGED_IDENTITY = "Managed Identity"
    ACCESS_TOKEN = "Access Token"  # noqa: S105 — auth-mode label, not a credential
    SERVICE_PRINCIPAL = "Service Principal (OAuth)"
    JWT_BEARER = "JWT Bearer Flow"
    CLIENT_CREDENTIALS = "Client Credentials Flow"
    SERVICE_ACCOUNT = "Service Account Key"


class Req(StrEnum):
    REQUIRED = "required"  # always required in this mode
    REQUIRED_UNLESS_URL = "required_unless_url"  # required only in host mode
    OPTIONAL = "optional"


@dataclass(frozen=True)
class ConnField:
    label: str  # exact UI form field label; a stable key consumers match on, not cosmetic text
    column: str  # Connection ORM attribute, or a key within ``parameters`` / ``secrets``
    requirement: Req
    secret: bool = False
    in_parameters: bool = False  # stored under the generic ``parameters`` column
    in_secrets: bool = False  # stored under the generic encrypted ``secrets`` column

    def __post_init__(self) -> None:
        # Read paths withhold a field on ``secret`` alone, so an unmarked field in the
        # secrets column would render its decrypted value into tool output.
        if self.in_secrets and not self.secret:
            raise ValueError(f"Connection field {self.label!r} is stored in secrets and must set secret=True.")


def read_conn_field(connection: Connection, fld: ConnField) -> object | None:
    if fld.in_parameters:
        return (connection.parameters or {}).get(fld.column)
    if fld.in_secrets:
        return (connection.secrets or {}).get(fld.column)
    return getattr(connection, fld.column, None)


def write_conn_field(connection: Connection, fld: ConnField, value: object) -> None:
    if fld.in_parameters:
        connection.parameters = {**(connection.parameters or {}), fld.column: value}
        return
    if fld.in_secrets:
        connection.secrets = {**(connection.secrets or {}), fld.column: value}
        return
    setattr(connection, fld.column, str(value) if fld.column == "project_port" and value is not None else value)


@dataclass(frozen=True)
class FlavorMode:
    mode: ConnectionMode | None  # None for single-auth flavors
    fields: tuple[ConnField, ...]  # excludes the URL field
    supports_url: bool  # whether the URL alternative is offered
    # Columns forced regardless of supplied params (auth flags, Databricks PAT user).
    sets: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FlavorSchema:
    code: str
    label: str
    modes: tuple[FlavorMode, ...]
    url_field: ConnField | None  # the shared URL field when any mode supports_url


_NON_TOKEN_CHARS = re.compile(r"[^a-z0-9]+")


# -- reusable field definitions ---------------------------------------------

_HOST = ConnField("Host", "project_host", Req.REQUIRED_UNLESS_URL)
_PORT = ConnField("Port", "project_port", Req.REQUIRED_UNLESS_URL)
_DATABASE = ConnField("Database", "project_db", Req.REQUIRED_UNLESS_URL)
_SERVICE_NAME = ConnField("Service Name", "project_db", Req.REQUIRED_UNLESS_URL)
_USERNAME = ConnField("Username", "project_user", Req.REQUIRED)
_PASSWORD_OPT = ConnField("Password", "project_pw_encrypted", Req.OPTIONAL, secret=True)
_PASSWORD_REQ = ConnField("Password", "project_pw_encrypted", Req.REQUIRED, secret=True)
_WAREHOUSE = ConnField("Warehouse", "warehouse", Req.OPTIONAL)
_PRIVATE_KEY = ConnField("Private Key", "private_key", Req.REQUIRED, secret=True)
_PRIVATE_KEY_PASSPHRASE = ConnField("Private Key Passphrase", "private_key_passphrase", Req.OPTIONAL, secret=True)
URL_FIELD = ConnField("URL", "url", Req.REQUIRED)
_CLIENT_ID = ConnField("Client ID", "project_user", Req.REQUIRED)

# Databricks
_HTTP_PATH_RU = ConnField("HTTP Path", "http_path", Req.REQUIRED_UNLESS_URL)
_HTTP_PATH_REQ = ConnField("HTTP Path", "http_path", Req.REQUIRED)
_HOST_REQ = ConnField("Host", "project_host", Req.REQUIRED)
_PORT_REQ = ConnField("Port", "project_port", Req.REQUIRED)
_CATALOG = ConnField("Catalog", "project_db", Req.REQUIRED_UNLESS_URL)
_CATALOG_REQ = ConnField("Catalog", "project_db", Req.REQUIRED)
_ACCESS_TOKEN = ConnField("Access Token", "project_pw_encrypted", Req.REQUIRED, secret=True)
_CLIENT_SECRET = ConnField("Client Secret", "project_pw_encrypted", Req.REQUIRED, secret=True)

# mssql
_TENANT_ID = ConnField("Tenant ID", "project_user", Req.REQUIRED)

# BigQuery / Salesforce
_SERVICE_ACCOUNT_KEY = ConnField("Service Account Key", "service_account_key", Req.REQUIRED, secret=True)
_LOGIN_URL = ConnField("Login URL", "project_host", Req.REQUIRED)
_CONSUMER_KEY = ConnField("Consumer Key", "project_user", Req.REQUIRED)
_SF_USERNAME = ConnField("Username", "project_db", Req.REQUIRED)
_CONSUMER_SECRET = ConnField("Consumer Secret", "project_pw_encrypted", Req.REQUIRED, secret=True)

# DuckDB
_DATABASE_FILE = ConnField("Database File", "database_file", Req.REQUIRED, in_parameters=True)

# Files
_BASE_PATH = ConnField("Base Path", "base_path", Req.REQUIRED, in_parameters=True)


def _host_auth_schema(code: str, *, db_field: ConnField = _DATABASE) -> FlavorSchema:
    """Single-mode host/URL flavors (PostgreSQL, Redshift, MSSQL, Oracle, SAP HANA)."""
    return FlavorSchema(
        code=code,
        label=FLAVOR_CODE_TO_LABEL[code],
        modes=(
            FlavorMode(mode=None, fields=(_HOST, _PORT, db_field, _USERNAME, _PASSWORD_OPT), supports_url=True),
        ),
        url_field=URL_FIELD,
    )


def _azure_schema(
    code: str,
    *,
    include_password: bool = True,
    include_service_principal: bool = False,
    url_field: ConnField | None = URL_FIELD,
) -> FlavorSchema:
    """Build a FlavorSchema for one of the MSSQL-family flavors. Managed
    Identity is always offered; ``include_password`` / ``include_service_principal``
    toggle the other two modes; ``url_field=None`` disables URL-mode connect.
    """
    modes: list[FlavorMode] = []
    if include_password:
        modes.append(FlavorMode(
            mode=ConnectionMode.PASSWORD,
            fields=(_HOST, _PORT, _DATABASE, _USERNAME, _PASSWORD_OPT),
            supports_url=url_field is not None,
            sets={"connect_with_identity": False, "connect_with_service_principal": False},
        ))
    modes.append(FlavorMode(
        mode=ConnectionMode.MANAGED_IDENTITY,
        fields=(_HOST, _PORT, _DATABASE),
        supports_url=url_field is not None,
        sets={"connect_with_identity": True, "connect_with_service_principal": False},
    ))
    if include_service_principal:
        modes.append(FlavorMode(
            mode=ConnectionMode.SERVICE_PRINCIPAL,
            fields=(_HOST, _PORT, _DATABASE, _CLIENT_ID, _TENANT_ID, _CLIENT_SECRET),
            supports_url=False,
            sets={"connect_with_identity": False, "connect_with_service_principal": True},
        ))
    return FlavorSchema(
        code=code,
        label=FLAVOR_CODE_TO_LABEL[code],
        modes=tuple(modes),
        url_field=url_field,
    )


FLAVOR_CONNECTION_SCHEMA: dict[str, FlavorSchema] = {
    "postgresql": _host_auth_schema("postgresql"),
    "redshift": _host_auth_schema("redshift"),
    "redshift_spectrum": _host_auth_schema("redshift_spectrum"),
    "mssql": _host_auth_schema("mssql"),
    "oracle": _host_auth_schema("oracle", db_field=_SERVICE_NAME),
    "sap_hana": _host_auth_schema("sap_hana"),
    "duckdb": FlavorSchema(
        code="duckdb",
        label=FLAVOR_CODE_TO_LABEL["duckdb"],
        modes=(FlavorMode(mode=None, fields=(_DATABASE_FILE,), supports_url=False),),
        url_field=None,
    ),
    "files": FlavorSchema(
        code="files",
        label=FLAVOR_CODE_TO_LABEL["files"],
        modes=(FlavorMode(mode=None, fields=(_BASE_PATH,), supports_url=False),),
        url_field=None,
    ),
    "azure_mssql": _azure_schema("azure_mssql", include_service_principal=True),
    "synapse_mssql": _azure_schema("synapse_mssql", include_service_principal=True),
    "onelake_mssql": _azure_schema(
        "onelake_mssql",
        include_password=False,
        include_service_principal=True,
        url_field=None,
    ),
    "snowflake": FlavorSchema(
        code="snowflake",
        label=FLAVOR_CODE_TO_LABEL["snowflake"],
        modes=(
            FlavorMode(
                mode=ConnectionMode.KEY_PAIR,
                fields=(_HOST, _PORT, _DATABASE, _USERNAME, _WAREHOUSE, _PRIVATE_KEY, _PRIVATE_KEY_PASSPHRASE),
                supports_url=True,
                sets={"connect_by_key": True},
            ),
            FlavorMode(
                mode=ConnectionMode.PASSWORD,
                fields=(_HOST, _PORT, _DATABASE, _USERNAME, _WAREHOUSE, _PASSWORD_REQ),
                supports_url=True,
                sets={"connect_by_key": False},
            ),
        ),
        url_field=URL_FIELD,
    ),
    "databricks": FlavorSchema(
        code="databricks",
        label=FLAVOR_CODE_TO_LABEL["databricks"],
        modes=(
            FlavorMode(
                mode=ConnectionMode.ACCESS_TOKEN,
                fields=(_HOST, _PORT, _HTTP_PATH_RU, _CATALOG, _ACCESS_TOKEN),
                supports_url=True,
                # PAT auth: the username is always the literal 'token'.
                sets={"connect_by_key": False, "project_user": "token"},
            ),
            FlavorMode(
                mode=ConnectionMode.SERVICE_PRINCIPAL,
                fields=(_HOST_REQ, _PORT_REQ, _HTTP_PATH_REQ, _CATALOG_REQ, _CLIENT_ID, _CLIENT_SECRET),
                supports_url=False,
                sets={"connect_by_key": True},
            ),
        ),
        url_field=URL_FIELD,
    ),
    "bigquery": FlavorSchema(
        code="bigquery",
        label=FLAVOR_CODE_TO_LABEL["bigquery"],
        modes=(FlavorMode(mode=None, fields=(_SERVICE_ACCOUNT_KEY,), supports_url=False),),
        url_field=None,
    ),
    "salesforce_data360": FlavorSchema(
        code="salesforce_data360",
        label=FLAVOR_CODE_TO_LABEL["salesforce_data360"],
        modes=(
            FlavorMode(
                mode=ConnectionMode.JWT_BEARER,
                fields=(_LOGIN_URL, _CONSUMER_KEY, _SF_USERNAME, _PRIVATE_KEY),
                supports_url=False,
                sets={"connect_by_key": True},
            ),
            FlavorMode(
                mode=ConnectionMode.CLIENT_CREDENTIALS,
                fields=(_LOGIN_URL, _CONSUMER_KEY, _CONSUMER_SECRET),
                supports_url=False,
                sets={"connect_by_key": False},
            ),
        ),
        url_field=None,
    ),
}


def schema_for(code: str) -> FlavorSchema:
    """Return the connection schema for a flavor code. Raises ``KeyError`` if unknown."""
    return FLAVOR_CONNECTION_SCHEMA[code]


# Every column any flavor treats as a credential. Surfaces that render a connection
# filter on this rather than listing the columns themselves, so a column added to the
# schema without ``secret=True`` cannot reach a response by being forgotten.
SECRET_COLUMNS: frozenset[str] = frozenset(
    fld.column
    for schema in FLAVOR_CONNECTION_SCHEMA.values()
    for mode in schema.modes
    for fld in mode.fields
    if fld.secret
)


def infer_mode(connection: Connection) -> ConnectionMode | None:
    """Reverse of a mode's ``sets`` flags — derive the active mode from a stored
    connection so update/validation can pick the right field set without the
    caller re-supplying ``connection_mode``.
    """
    code = connection.sql_flavor_code
    schema = FLAVOR_CONNECTION_SCHEMA.get(code)
    if schema is None or (len(schema.modes) == 1 and schema.modes[0].mode is None):
        return None

    if code in {"azure_mssql", "synapse_mssql"}:
        if connection.connect_with_service_principal:
            return ConnectionMode.SERVICE_PRINCIPAL
        return ConnectionMode.MANAGED_IDENTITY if connection.connect_with_identity else ConnectionMode.PASSWORD
    if code == "onelake_mssql":
        # Fabric SQL analytics endpoints reject SQL logins, so only the two Entra
        # modes are offered on this flavor. Default to SPN if neither flag is set
        # (external client is the common case), so validate_connection_fields
        # complains about the SPN-required fields rather than a nonexistent
        # password mode.
        if connection.connect_with_identity:
            return ConnectionMode.MANAGED_IDENTITY
        return ConnectionMode.SERVICE_PRINCIPAL
    if code == "snowflake":
        return ConnectionMode.KEY_PAIR if connection.connect_by_key else ConnectionMode.PASSWORD
    if code == "databricks":
        return ConnectionMode.SERVICE_PRINCIPAL if connection.connect_by_key else ConnectionMode.ACCESS_TOKEN
    if code == "salesforce_data360":
        return ConnectionMode.JWT_BEARER if connection.connect_by_key else ConnectionMode.CLIENT_CREDENTIALS
    return None


def _mode_for_connection(connection: Connection) -> FlavorMode:
    """Pick the FlavorMode matching a connection's current flags (for validation)."""
    schema = schema_for(connection.sql_flavor_code)
    if len(schema.modes) == 1:
        return schema.modes[0]
    active = infer_mode(connection)
    for fmode in schema.modes:
        if fmode.mode == active:
            return fmode
    return schema.modes[0]


def connection_display_fields(connection: Connection) -> list[ConnField]:
    """Active-mode fields (plus the URL field when in URL mode), in schema order.

    For rendering a connection back to the user with the flavor-specific UI label
    for each populated column (e.g. ``Catalog`` for Databricks, ``Login URL`` for
    Salesforce). Callers skip secrets and empty values.
    """
    schema = schema_for(connection.sql_flavor_code)
    fields = list(_mode_for_connection(connection).fields)
    if schema.url_field is not None and getattr(connection, "connect_by_url", False):
        fields.append(schema.url_field)
    return fields


def _split_spn_identity(connection: Connection, fields: list[ConnField]) -> tuple[str | None, str | None]:
    """Unpack ``project_user`` into its client and tenant halves, or ``(None, None)``
    when the active mode does not pack two fields into that column.
    """
    packed = {_CLIENT_ID.label, _TENANT_ID.label}.issubset(
        {fld.label for fld in fields if fld.column == "project_user"}
    )
    if not packed:
        return None, None
    stored = connection.project_user or ""
    if "@" not in stored:
        return "", ""
    client_id, _, tenant_id = stored.partition("@")
    return client_id, tenant_id


def connection_display_values(connection: Connection) -> list[tuple[ConnField, object]]:
    """Populated, non-secret ``(field, value)`` pairs in schema order.

    Secret fields and empty values are dropped, and the mssql-family Service
    Principal identity is split back into its two fields.
    """
    fields = connection_display_fields(connection)
    spn_client_id, spn_tenant_id = _split_spn_identity(connection, fields)

    values: list[tuple[ConnField, object]] = []
    for fld in fields:
        if fld.secret:
            continue
        value: object
        if spn_client_id is not None and fld.label == _CLIENT_ID.label:
            value = spn_client_id
        elif spn_tenant_id is not None and fld.label == _TENANT_ID.label:
            value = spn_tenant_id
        else:
            value = read_conn_field(connection, fld)
        if value in (None, ""):
            continue
        values.append((fld, value))
    return values


def settings_key(label: str) -> str:
    """The snake_case token a field label is published under."""
    return _NON_TOKEN_CHARS.sub("_", label.lower()).strip("_")


def connection_field_labels(connection: Connection) -> dict[str, str]:
    """Map each ``Connection`` column to its flavor/mode-specific UI label.

    Used to label diff output. Columns outside the active mode fall back to the
    caller's generic labels.
    """
    schema = schema_for(connection.sql_flavor_code)
    fields = _mode_for_connection(connection).fields
    labels: dict[str, str] = {}
    for fld in fields:
        if fld.column in labels:
            # Two labels sharing one column: combine so the diff reads honestly.
            labels[fld.column] = f"{labels[fld.column]} / {fld.label}"
        else:
            labels[fld.column] = fld.label
    if schema.url_field is not None:
        labels[schema.url_field.column] = schema.url_field.label
    return labels

# -- field-requirement validation -------------------------------------------

_CONNECTION_NAME_MIN = 3
_CONNECTION_NAME_MAX = 40
_MAX_THREADS_MIN = 1
_MAX_THREADS_MAX = 8
_MAX_QUERY_CHARS_MIN = 500
_MAX_QUERY_CHARS_MAX = 50000


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _required_fields_for(connection: Connection) -> list[ConnField]:
    """Schema fields that must be non-empty for this connection's flavor + active
    mode, accounting for the URL alternative.
    """
    fmode = _mode_for_connection(connection)
    using_url = fmode.supports_url and bool(connection.connect_by_url)

    required: list[ConnField] = []
    for fld in fmode.fields:
        if fld.requirement is Req.REQUIRED:
            required.append(fld)
        elif fld.requirement is Req.REQUIRED_UNLESS_URL and not using_url:
            required.append(fld)

    schema = schema_for(connection.sql_flavor_code)
    if using_url and schema.url_field is not None:
        required.append(schema.url_field)
    return required


def validate_connection_fields(connection: Connection) -> list[str]:
    """Return every validation error (empty list = valid).

    Mirrors the per-flavor JS form validators in
    ``ui/static/js/components/connection_form.js``. The connection tools call this
    and raise their user-facing error containing the bullets. Field errors use the
    UI label (e.g. ``Host``) so the LLM sees the same wording as a UI user.
    """
    errors: list[str] = []
    flavor_label = FLAVOR_CODE_TO_LABEL.get(connection.sql_flavor_code, connection.sql_flavor_code)

    name = connection.connection_name
    if _missing(name):
        errors.append("`connection_name` is required.")
    elif not (_CONNECTION_NAME_MIN <= len(name.strip()) <= _CONNECTION_NAME_MAX):
        errors.append(
            f"`connection_name` must be between {_CONNECTION_NAME_MIN} and {_CONNECTION_NAME_MAX} characters."
        )

    for fld in _required_fields_for(connection):
        if _missing(read_conn_field(connection, fld)):
            errors.append(f"`{fld.label}` is required for {flavor_label}.")

    threads = connection.max_threads
    if threads is not None and not (_MAX_THREADS_MIN <= threads <= _MAX_THREADS_MAX):
        errors.append(f"`max_threads` must be between {_MAX_THREADS_MIN} and {_MAX_THREADS_MAX}.")

    query_chars = connection.max_query_chars
    if query_chars is not None and not (_MAX_QUERY_CHARS_MIN <= query_chars <= _MAX_QUERY_CHARS_MAX):
        errors.append(f"`max_query_chars` must be between {_MAX_QUERY_CHARS_MIN} and {_MAX_QUERY_CHARS_MAX}.")

    return errors


def authentication_method(connection: Connection) -> ConnectionMode | None:
    """The connection's auth method: the active connection mode for multi-mode
    flavors, else the implicit method (service account key, else password).

    ``None`` for a flavor that declares no credential of any kind, where naming a method
    would describe one the connection does not have.
    """
    mode = infer_mode(connection)
    if mode is not None:
        return mode
    if connection.service_account_key:
        return ConnectionMode.SERVICE_ACCOUNT
    schema = FLAVOR_CONNECTION_SCHEMA.get(connection.sql_flavor_code)
    if schema and not any(fld.secret for flavor_mode in schema.modes for fld in flavor_mode.fields):
        return None
    return ConnectionMode.PASSWORD


def authentication_label(connection: Connection) -> str | None:
    """Display label for the connection's auth method, or ``None`` when it has none."""
    method = authentication_method(connection)
    return str(method) if method is not None else None
