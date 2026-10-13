import re
from abc import abstractmethod
from collections.abc import Callable, Iterable
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
    project_pw_encrypted: bytes
    url: str
    connect_by_url: bool
    connect_by_key: bool
    private_key: bytes
    private_key_passphrase: bytes
    http_path: str
    warehouse: str
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


def resolve_connection_params(
    connection_params: ConnectionParams, table_group_schema: str | None = None
) -> ResolvedConnectionParams:
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
        dbschema=table_group_schema,
        sql_flavor=sql_flavor,
        sql_flavor_code=connection_params.get("sql_flavor_code") or sql_flavor,
        connect_by_key=connection_params.get("connect_by_key", False),
        private_key=_decrypt_if_needed(connection_params.get("private_key")),
        private_key_passphrase=_decrypt_if_needed(connection_params.get("private_key_passphrase")),
        http_path=connection_params.get("http_path") or "",
        warehouse=connection_params.get("warehouse") or "",
        service_account_key=connection_params.get("service_account_key"),
        connect_with_identity=connection_params.get("connect_with_identity") or False,
        connect_with_service_principal=connection_params.get("connect_with_service_principal") or False,
        parameters=connection_params.get("parameters") or {},
        secrets=connection_params.get("secrets") or {},
    )


def base_type_name(type_name: str | None) -> str:
    """Return a catalog type name lowercased, with any precision or length removed."""
    return re.sub(r"\s*\([^)]*\)", "", type_name or "").strip().lower()


def exact_float_canonical(
    column_ref: str,
    double_type: str,
    integer_type: str,
    quotient: Callable[[str, str], str],
    bigint_type: str = "BIGINT",
) -> str:
    """Return the SQL expression for a binary float's canonical number, computed from its exact value.

    The magnitude splits exactly into a multiple of 2^40, a whole remainder and a fraction, and the
    fraction into two 45-bit integers, so integer arithmetic sees the exact binary value. The value
    rounds half away from zero to nine decimal places, and then to six, as ``value_hash.canonical_text``
    does. Exact for every magnitude below 10^29 and at least 2^-38; a smaller value rounds to zero.

    Args:
        column_ref: The quoted column reference.
        double_type: The engine's double-precision type.
        integer_type: An exact integer or decimal type that holds 10^38.
        quotient: Builds the engine's truncating division of two non-negative integers of that type.
        bigint_type: An integer type that holds every whole number below 2^63.

    Returns:
        The value rounded to six decimal places, times 10^6, as an integer of ``integer_type``.
    """

    def exact(expr: str) -> str:
        # Every operand is a whole number below 2^63, so the cast is exact
        return f"CAST(CAST({expr} AS {bigint_type}) AS {integer_type})"

    def power(exponent: int) -> str:
        return f"CAST({2**exponent} AS {double_type})"

    magnitude = f"ABS(CAST({column_ref} AS {double_type}))"
    high = f"FLOOR({magnitude} / {power(40)})"
    low = f"({magnitude} - {high} * {power(40)})"
    fraction_high = f"FLOOR(({low} - FLOOR({low})) * {power(45)})"
    fraction_low = f"((({low} - FLOOR({low})) * {power(45)} - {fraction_high}) * {power(45)})"
    whole = f"({exact(high)} * {2**40} + {exact(f'FLOOR({low})')})"
    fraction_bits = f"({exact(fraction_high)} * {2**45} + {exact(fraction_low)})"
    nanos = quotient(f"{fraction_bits} * 1000000000 + {2**89}", str(2**90))
    micros = f"{whole} * 1000000 + {quotient(f'{nanos} + 500', '1000')}"
    return f"(CASE WHEN {column_ref} < 0 THEN -1 ELSE 1 END) * ({micros})"


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

    # Catalog column types (lowercase) of general type X that the engine compares for equality, so
    # profiling counts their distinct values directly rather than over a text form
    distinct_countable_x_types: frozenset[str] = frozenset()

    # Catalog column types (lowercase) of integer or decimal columns that profiling computes no
    # exact sum for: floating-point types the catalog marks decimal, or types with no cast to decimal
    exact_sum_excluded_types: frozenset[str] = frozenset()

    # Whether profiling and the comparison tests hash values on this engine. A flavor that sets it
    # implements the value-hash primitives: hex_to_wide_decimal, utc_timestamp, format_timestamp and
    # epoch_seconds. A flavor that can hash text only on some versions also gives a probe query.
    supports_value_hash = False
    text_hash_probe: str | None = None

    # Base names (lowercase, without precision) of the engine's binary floating-point types, whose
    # values are cast to a decimal before their canonical text so they hash like the same decimals
    float_types: frozenset[str] = frozenset()
    # Floats are widened to this type before the cast, so a single-precision value converts exactly
    double_type = "DOUBLE PRECISION"

    wide_decimal_type = "DECIMAL(38,0)"

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

    def numeric_value(self, column_ref: str, column_type: str | None) -> str:  # noqa: ARG002
        """Return the SQL expression that reads a numeric column's value as a number.

        Args:
            column_ref: The quoted column reference.
            column_type: The column's type as recorded in the data catalog.

        Returns:
            ``column_ref``, or a cast of it for a numeric type the flavor cannot compare with
            plain numbers or apply arithmetic functions to.
        """
        return column_ref

    def is_float(self, column: ColumnChars) -> bool:
        """Whether a column's catalog type is one of the engine's binary floating-point types."""
        return base_type_name(column.db_data_type or column.column_type) in self.float_types

    def value_hash_params(self, column: ColumnChars | None, key_column: ColumnChars | None = None) -> dict[str, str]:
        """Return the template parameters that compute a column's value hashes.

        Args:
            column: The column's catalog characteristics.
            key_column: The catalog characteristics of its table's key column, if it has one.

        Returns:
            ``MULTISET_HASH_TERM``; ``EPOCH_SUM_TERM`` for a date column; ``KEYED_HASH_TERM`` when
            ``key_column`` is given. Empty when the flavor does not hash values or there is no column.
        """
        if not (self.supports_value_hash and column):
            return {}
        quote = self.quote_character
        column_ref = f"{quote}{column.column_name}{quote}"
        params = {"MULTISET_HASH_TERM": self.multiset_hash_term(column_ref, column)}
        if column.general_type == "D":
            params["EPOCH_SUM_TERM"] = self.epoch_sum_term(column_ref, column)
        if key_column:
            key_ref = f"{quote}{key_column.column_name}{quote}"
            params["KEYED_HASH_TERM"] = self.keyed_hash_term(key_ref, key_column, column_ref, column)
        return params

    def multiset_hash_term(self, column_ref: str, column: ColumnChars) -> str:
        """Return the SQL expression for one value's term in the column's multiset hash sum.

        Args:
            column_ref: The quoted column reference.
            column: The column's catalog characteristics.

        Returns:
            The first 56 bits of the MD5 of the value's canonical text, as the wide decimal type, or
            NULL for a value ``hashable_condition`` excludes.
        """
        hashed = self.hash_integer(self.canonical_text(column_ref, column))
        return f"CASE WHEN {self.hashable_condition(column_ref, column)} THEN {hashed} END"

    def keyed_hash_term(self, key_ref: str, key_column: ColumnChars, column_ref: str, column: ColumnChars) -> str:
        """Return the SQL expression for one row's term in a column's keyed hash sum.

        The hashed text joins the MD5 hex of the key's and the value's canonical texts. Both digests
        have a fixed width, so two different key and value pairs never produce the same text. A row
        with a NULL value contributes NULL.
        """
        key_hex = self.md5_hex(self.canonical_text(key_ref, key_column))
        value_hex = self.md5_hex(self.canonical_text(column_ref, column))
        hashed = self.hash_integer(f"{key_hex} {self.concat_operator} {value_hex}")
        condition = f"{self.hashable_condition(column_ref, column)} AND {self.hashable_condition(key_ref, key_column)}"
        return f"CASE WHEN {condition} THEN {hashed} END"

    def hashable_condition(self, column_ref: str, column: ColumnChars) -> str:
        """Return the SQL condition under which a value contributes to the column's hashes.

        A NULL never contributes. Neither does a number too large for the decimal its canonical text
        is computed in: 10^29 or more in magnitude for a binary float, and for another number one that
        rounds to 10^32 or more at six places. An infinite or NaN value fails the same comparison.
        """
        # Guarded explicitly: some engines hash NULL or concatenate it as an empty string
        if column.general_type == "N" and self.is_float(column):
            return f"{column_ref} IS NOT NULL AND ABS({column_ref}) < 1E29"
        if column.general_type == "N":
            # Compared as whole numbers: a float bound rounds a decimal near it, and some engines cast
            # a decimal bound to the column's own type, which may not hold it. No ABS, which overflows
            # on an integer type's minimum value.
            below = f"CAST(FLOOR({column_ref}) AS {self.wide_decimal_type}) < {10**32}"
            above = f"CAST(CEIL({column_ref}) AS {self.wide_decimal_type}) > {-(10**32)}"
            return f"{column_ref} IS NOT NULL AND {below} AND {above}"
        return f"{column_ref} IS NOT NULL"

    def epoch_sum_term(self, column_ref: str, column: ColumnChars) -> str:
        """Return the SQL expression for one date value in seconds since 1970-01-01 UTC, truncated."""
        seconds = f"CAST({self.epoch_seconds(self.utc_timestamp(column_ref, column))} AS {self.wide_decimal_type})"
        return f"CASE WHEN {self.hashable_condition(column_ref, column)} THEN {seconds} END"

    def canonical_text(self, column_ref: str, column: ColumnChars) -> str:
        """Return the SQL expression for a value's canonical text, which renders identical values
        identically on every engine.

        Text is the value as read by ``text_value``. A number is its value rounded half away from zero
        to six decimal places, times 10^6, as integer text; a binary float is first rounded to nine
        places, which absorbs its representation error. A date or timestamp is ``YYYY-MM-DD HH24:MI:SS`` in UTC,
        truncated to the second.
        """
        if column.general_type == "N":
            return self.canonical_number(column_ref, self.is_float(column))
        if column.general_type == "D":
            return self.format_timestamp(self.utc_timestamp(column_ref, column))
        return self.text_value(column_ref, column.column_type)

    def canonical_number(self, column_ref: str, is_float: bool) -> str:
        exact = self.float_to_decimal(column_ref) if is_float else column_ref
        rounded = f"CAST(ROUND({exact}, 6) AS DECIMAL(38,6))"
        # Scaled in two parts: multiplying the decimal by 10^6 keeps its scale on some engines and overflows past 10^26.
        # Split from the magnitude: FLOOR takes a negative value just above -10^32 to a 33-digit whole part.
        magnitude = f"ABS({rounded})"
        whole = f"CAST(FLOOR({magnitude}) AS {self.wide_decimal_type}) * 1000000"
        fraction = f"CAST(({magnitude} - FLOOR({magnitude})) * 1000000 AS {self.wide_decimal_type})"
        sign = f"CAST(SIGN({rounded}) AS {self.wide_decimal_type})"
        return f"CAST({sign} * ({whole} + {fraction}) AS {self.varchar_type})"

    def float_to_decimal(self, column_ref: str) -> str:
        """Return the SQL expression converting a binary float to ``DECIMAL(38,9)``."""
        return f"CAST(CAST({column_ref} AS {self.double_type}) AS DECIMAL(38,9))"

    def md5_hex(self, text_expr: str) -> str:
        """Return the SQL expression for the lowercase hex MD5 of the UTF-8 bytes of ``text_expr``."""
        return f"MD5({text_expr})"

    def hash_integer(self, text_expr: str) -> str:
        """Return the SQL expression for the first 56 bits of the MD5 of ``text_expr``, as the wide
        decimal type. 56 bits fit a signed 64-bit integer as a positive value on every engine.
        """
        return self.hex_to_wide_decimal(f"SUBSTRING({self.md5_hex(text_expr)}, 1, 14)")

    def hex_to_wide_decimal(self, hex_expr: str) -> str:
        """Return the SQL expression converting 14 lowercase hex digits to the wide decimal type."""
        raise NotImplementedError

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        """Return the SQL expression for a date or timestamp value as a timestamp without time zone,
        holding the UTC wall-clock time when the value is time-zone aware.
        """
        raise NotImplementedError

    def format_timestamp(self, timestamp_expr: str) -> str:
        """Return the SQL expression rendering a timestamp as ``YYYY-MM-DD HH24:MI:SS``, truncated."""
        raise NotImplementedError

    def epoch_seconds(self, timestamp_expr: str) -> str:
        """Return the SQL expression for a timestamp's whole seconds since 1970-01-01, truncated."""
        raise NotImplementedError

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

    def caches_tables(self, sql_flavor_code: str) -> bool:  # noqa: ARG002
        """Whether ``cache_tables`` keeps local copies for this connection type."""
        return False

    def cache_tables(
        self,
        connection: Connection,
        params: ResolvedConnectionParams,
        declarations: list[FileDeclaration],
        table_names: Iterable[str],
    ) -> None:
        """Keep a local copy of the named tables for the rest of this connection's life.

        Does nothing by default: a flavor reads its tables where they are.
        """

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

    def create_engine(self, connection_params: ConnectionParams, table_group_schema: str | None = None) -> Engine:
        """Create an engine for the connection.

        :param connection_params: The connection's stored parameters.
        :param table_group_schema: Schema of the table group the engine reads for, or None when it reads for none.
        """
        params = resolve_connection_params(connection_params, table_group_schema)
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
