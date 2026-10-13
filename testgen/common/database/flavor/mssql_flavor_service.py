import re

from sqlalchemy.engine import URL

from testgen import settings
from testgen.common.database.column_chars import ColumnChars, ObjectType
from testgen.common.database.flavor.flavor_service import (
    FlavorService,
    ResolvedConnectionParams,
    base_type_name,
    exact_float_canonical,
)


class MssqlFlavorService(FlavorService):

    concat_operator = "+"
    escaped_underscore = "[_]"
    row_limiting_clause = "top"
    # A plain literal is converted to the database code page, which drops characters outside it.
    string_literal_prefix = "N"
    url_scheme = "mssql+pyodbc"

    # APPROX_PERCENTILE_CONT arrived in SQL Server 2022; older servers fail the probe and stay exact.
    supports_approx_percentile = True
    approx_percentile_probe = "SELECT APPROX_PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY n) FROM (SELECT 1 AS n) AS t"

    supports_value_hash = True
    # Text is hashed as UTF-8, which only the UTF-8 collations of SQL Server 2019 and later produce
    text_hash_probe = "SELECT HASHBYTES('MD5', CAST(N'x' COLLATE Latin1_General_100_BIN2_UTF8 AS VARCHAR(10)))"
    float_types = frozenset({"float", "real"})
    double_type = "FLOAT"

    def sampleable_object_types(self, sql_flavor_code: str) -> frozenset[ObjectType] | None:
        # Fabric rejects TABLESAMPLE; SQL Server accepts it only on base tables.
        if sql_flavor_code == "onelake_mssql":
            return frozenset()
        return frozenset({ObjectType.TABLE})

    def table_hint(self, sql_flavor_code: str) -> str:
        # Fabric rejects WITH (NOLOCK).
        if sql_flavor_code == "onelake_mssql":
            return ""
        return "WITH (NOLOCK)"

    def text_value(self, column_ref: str, column_type: str | None) -> str:
        # CHAR and NCHAR values are stored padded with spaces to the declared length.
        if column_type and re.fullmatch(r"n?char(\(\d+\))?", column_type.lower()):
            return f"RTRIM({column_ref})"
        return column_ref

    def canonical_text(self, column_ref: str, column: ColumnChars) -> str:
        text = super().canonical_text(column_ref, column)
        if column.general_type == "A":
            return f"CAST(CAST({text} AS NVARCHAR(MAX)) COLLATE Latin1_General_100_BIN2_UTF8 AS VARCHAR(MAX))"
        return text

    def canonical_number(self, column_ref: str, is_float: bool) -> str:
        if is_float:
            # A direct cast keeps only 17 significant digits
            canonical = exact_float_canonical(
                column_ref, self.double_type, "DECIMAL(38,0)", lambda a, b: f"(({a}) - ({a}) % {b}) / {b}"
            )
            return f"CAST(CAST({canonical} AS DECIMAL(38,0)) AS {self.varchar_type})"
        # The cast rounds half away from zero; ROUND keeps the column's precision, which overflows when
        # rounding adds a whole digit. Decimal arithmetic here can drop the scale; the rounded value's
        # text with its point removed is exact.
        fixed = f"CAST(CAST({column_ref} AS DECIMAL(38,6)) AS VARCHAR(50))"
        return f"CAST(CAST(REPLACE({fixed}, '.', '') AS DECIMAL(38,0)) AS {self.varchar_type})"

    def hashable_condition(self, column_ref: str, column: ColumnChars) -> str:
        if column.general_type == "N" and not self.is_float(column):
            # Compared directly: FLOOR overflows money at its minimum value, and SQL Server converts
            # both sides to a decimal that holds them
            return f"{column_ref} IS NOT NULL AND {column_ref} < {10**32} AND {column_ref} > {-(10**32)}"
        return super().hashable_condition(column_ref, column)

    def md5_hex(self, text_expr: str) -> str:
        return f"LOWER(CONVERT(VARCHAR(32), HASHBYTES('MD5', {text_expr}), 2))"

    def hash_integer(self, text_expr: str) -> str:
        return f"CAST(CONVERT(BIGINT, SUBSTRING(HASHBYTES('MD5', {text_expr}), 1, 7)) AS {self.wide_decimal_type})"

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        if base_type_name(column.db_data_type) == "datetimeoffset":
            return f"CAST(SWITCHOFFSET({column_ref}, '+00:00') AS DATETIME2)"
        return f"CAST({column_ref} AS DATETIME2)"

    def format_timestamp(self, timestamp_expr: str) -> str:
        return f"CONVERT(VARCHAR(19), {timestamp_expr}, 120)"

    def epoch_seconds(self, timestamp_expr: str) -> str:
        # Azure Synapse has no DATEDIFF_BIG, and DATEDIFF overflows INT in seconds; days and seconds into the day fit
        days = f"DATEDIFF(DAY, CAST('1970-01-01' AS DATETIME2), {timestamp_expr})"
        seconds = f"DATEDIFF(SECOND, CAST(CAST({timestamp_expr} AS DATE) AS DATETIME2), {timestamp_expr})"
        return f"CAST({days} AS BIGINT) * 86400 + {seconds}"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        connection_url = URL.create(
            self.url_scheme,
            username=params.username,
            password=params.password or "",
            host=params.host,
            port=int(params.port or 1433),
            database=params.dbname,
            query={
                "driver": "ODBC Driver 18 for SQL Server",
            },
        )

        if params.connect_with_identity:
            connection_url = connection_url._replace(username=None, password=None).update_query_dict({
                "encrypt": "yes",
                "authentication": "ActiveDirectoryMsi",
            })

        # ODBC Driver 18 masks an Entra token-exchange failure as an HYT00
        # login-timeout unless TrustServerCertificate is set explicitly.
        if params.connect_with_service_principal:
            connection_url = connection_url.update_query_dict({
                "encrypt": "yes",
                "trustservercertificate": "no",
                "authentication": "ActiveDirectoryServicePrincipal",
                "connectretrycount": "4",
            })

        return connection_url.render_as_string(hide_password=False)

    def get_pre_connection_queries(self, params: ResolvedConnectionParams) -> list[tuple[str, dict | None]]:
        # Synapse dedicated SQL pool rejects these SET commands: ANSI_DEFAULTS isn't
        # implemented, ANSI_WARNINGS can't be turned off, and only READ UNCOMMITTED
        # isolation is allowed (and is the default). Each one would log a warning.
        if params.sql_flavor_code == "synapse_mssql":
            return []

        # ANSI_DEFAULTS turns on ANSI_NULLS / ANSI_PADDING / QUOTED_IDENTIFIER (good)
        # *and* ANSI_WARNINGS (bad here). pyodbc>=5.2 escalates SQL Server's 01003
        # "Null value is eliminated by an aggregate" warning into a pyodbc.Error,
        # which breaks profiling/CAT queries that aggregate over nullable columns.
        # Target connections are read-only, so disabling ANSI_WARNINGS is safe.
        return [
            ("SET ANSI_DEFAULTS ON;", None),
            ("SET ANSI_WARNINGS OFF;", None),
            ("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;", None),
        ]

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:
        # Imported here rather than at module scope: pyodbc requires the unixODBC native
        # library (libodbc), which is absent in some environments that import this module
        # (e.g. the unit-test image) but always present where a SQL Server connection is
        # actually made — which is the only path that reaches this method.
        import pyodbc

        # Let SQLAlchemy's pool be the sole owner of connection lifecycle. pyodbc enables
        # ODBC-driver-manager pooling by default, so a connection SQLAlchemy discards can be
        # retained by the ODBC pool and left sleeping on the server with its transaction
        # state unreset until the next checkout. Setting this during engine creation is
        # before the first connection, which is when it must be set.
        pyodbc.pooling = False

        # pyodbc defaults to autocommit=False, which opens an implicit transaction on the
        # first statement (including the pre-connection SET queries) and holds it until
        # commit/rollback/close. TestGen only reads from target databases, so there is no
        # multi-statement transaction to preserve, and running in autocommit keeps a
        # connection from sitting idle on the server holding an open transaction. This must
        # be set at connect time: SQLAlchemy 2.x raises if the isolation level is changed
        # after a statement has autobegun a transaction.
        connect_args = super().get_connect_args(params)
        connect_args["autocommit"] = True
        if settings.SKIP_DATABASE_CERTIFICATE_VERIFICATION:
            connect_args["TrustServerCertificate"] = "yes"
        return connect_args
