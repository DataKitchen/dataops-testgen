import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from testgen.common.database.file_declarations import NAME_INVALID, URI_IS_FOLDER, parse_file_declarations
from testgen.common.database.flavor import duckdb_flavor_service
from testgen.common.database.flavor.duckdb_flavor_service import (
    ATTACHED_CATALOG,
    AttachFailure,
    DuckdbConnectionError,
    DuckdbFlavorService,
    attach_error_message,
    classify_attach_error,
)
from testgen.common.database.flavor.flavor_service import resolve_connection_params
from testgen.common.flavors import (
    FLAVOR_CODE_TO_FAMILY,
    FLAVOR_CODE_TO_LABEL,
    SqlFlavorCode,
    declares_files,
    fixed_table_group_schema,
)


@pytest.fixture
def customer_database(tmp_path):
    path = tmp_path / "customer.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("CREATE SCHEMA sales")
    connection.execute("CREATE TABLE sales.orders (id BIGINT, amount DECIMAL(12,4), placed_at TIMESTAMP)")
    connection.execute("INSERT INTO sales.orders VALUES (1, 10.5, TIMESTAMP '2026-01-02 03:04:05')")
    connection.execute("""
        CREATE TABLE sales.profiled AS
        SELECT 'alpha' AS note, CAST(1.25 AS DECIMAL(12,4)) AS amount,
               TIMESTAMP '2026-01-02 03:04:05' AS placed_at, TRUE AS shipped,
               CAST(NULL AS BLOB) AS payload,
               CAST('2026-01-02 03:04:05' AS TIMESTAMP_S) AS placed_at_s,
               CAST('2026-01-02 03:04:05' AS TIMESTAMP_MS) AS placed_at_ms,
               CAST('2026-01-02 03:04:05' AS TIMESTAMP_NS) AS placed_at_ns,
               CAST('2026-01-02 03:04:05' AS TIMESTAMPTZ) AS placed_at_tz,
               DATE '2026-01-02' AS placed_on,
               CAST(9 AS UBIGINT) AS unsigned_amount,
               CAST(9 AS VARINT) AS bignum_amount
    """)
    # Values below DECIMAL(18,3)'s resolution, which is what a NUMERIC cast would round to zero.
    connection.execute("""
        CREATE TABLE sales.tiny AS
        SELECT * FROM (VALUES (0.0004), (0.0006), (0.0), (1.23456), (-0.0002))
        AS t(rate)
    """)
    connection.close()
    return path


@pytest.fixture
def dead_pid() -> int:
    """A pid no process holds, so the sweep reads the directory as an orphan."""
    process = subprocess.Popen([sys.executable, "-c", ""])  # noqa: S603
    process.wait()
    return process.pid


def connection_params(database_file) -> dict:
    return {
        "sql_flavor": "duckdb",
        "sql_flavor_code": "duckdb",
        "parameters": {"database_file": str(database_file)},
    }


def test_duckdb_is_registered_as_its_own_family():
    assert FLAVOR_CODE_TO_FAMILY[SqlFlavorCode.DUCKDB] == "duckdb"
    assert FLAVOR_CODE_TO_LABEL[SqlFlavorCode.DUCKDB] == "DuckDB"


def test_the_connection_is_always_an_in_memory_database(customer_database):
    """The customer's file is attached, never opened as the default database, so it is never written."""
    service = DuckdbFlavorService()
    params = resolve_connection_params(connection_params(customer_database))
    assert service.get_connection_string(params) == "duckdb:///:memory:"


def test_connect_args_omit_the_timeout_duckdb_rejects():
    service = DuckdbFlavorService()
    params = resolve_connection_params(connection_params("unused.duckdb"))
    assert "connect_timeout" not in service.get_connect_args(params)


def test_the_engine_does_not_share_one_in_memory_database_across_checkouts():
    service = DuckdbFlavorService()
    params = resolve_connection_params(connection_params("unused.duckdb"))
    assert service.get_engine_args(params)["poolclass"] is NullPool


def test_attaching_exposes_the_customer_schemas_to_two_part_references(customer_database):
    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            assert connection.execute(text("SELECT count(*) FROM sales.orders")).scalar() == 1
            assert connection.execute(text("SELECT current_database()")).scalar() == ATTACHED_CATALOG
    finally:
        engine.dispose()


def test_the_attached_database_cannot_be_written(customer_database):
    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            with pytest.raises(Exception, match="read-only"):
                connection.execute(text("CREATE TABLE sales.written (x INT)"))
    finally:
        engine.dispose()


def test_a_quote_in_the_path_cannot_end_the_attach_literal(tmp_path):
    """The path reaches ATTACH as a literal rather than a bind parameter, so it is escaped."""
    service = DuckdbFlavorService()
    hostile = tmp_path / "a' AS x (READ_ONLY); ATTACH 'b"
    params = connection_params(hostile)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            with pytest.raises(DuckdbConnectionError) as caught:
                service.init(connection, resolve_connection_params(params), [])
            # The path is treated as one filename, so it fails as a missing file rather than parsing.
            assert caught.value.failure is AttachFailure.FILE_MISSING
    finally:
        engine.dispose()


def test_a_connection_with_no_database_file_fails_before_it_attaches():
    service = DuckdbFlavorService()
    params = {"sql_flavor": "duckdb", "sql_flavor_code": "duckdb", "parameters": {}}
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            with pytest.raises(DuckdbConnectionError, match="no database file configured"):
                service.init(connection, resolve_connection_params(params), [])
    finally:
        engine.dispose()


def test_a_missing_file_is_reported_as_missing(tmp_path):
    service = DuckdbFlavorService()
    params = connection_params(tmp_path / "absent.duckdb")
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            with pytest.raises(DuckdbConnectionError) as caught:
                service.init(connection, resolve_connection_params(params), [])
            assert caught.value.failure is AttachFailure.FILE_MISSING
            assert str(caught.value) == "The database file was not found at this path."
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (
            'IO Error: Could not set lock on file "/data/c.duckdb": Conflicting lock is held in '
            "/usr/bin/python3 (PID 11827) by user someone-else.",
            AttachFailure.LOCKED,
        ),
        (
            "Trying to read a database file with version number 65, but we can only read versions "
            "between 64 and 64.",
            AttachFailure.VERSION_MISMATCH,
        ),
        (
            'Error opening "/data/c.duckdb": file was written with a storage version greater than '
            "the latest version supported by this DuckDB instance.",
            AttachFailure.VERSION_MISMATCH,
        ),
        (
            'IO Error: Cannot open database "/data/c.duckdb" in read-only mode: database does not exist',
            AttachFailure.FILE_MISSING,
        ),
        ("Some entirely unfamiliar failure", AttachFailure.UNKNOWN),
        # Storage-version wording that is not a too-new database.
        (
            'VARIANT columns are not supported in storage versions prior to v1.4.0 (database "c" is '
            "using storage version v1.0.0)",
            AttachFailure.UNKNOWN,
        ),
    ],
)
def test_attach_failures_are_classified_from_duckdb_wording(detail, expected):
    assert classify_attach_error(Exception(detail)) is expected


def test_a_lock_conflict_message_does_not_leak_the_holding_process():
    detail = (
        'IO Error: Could not set lock on file "/data/c.duckdb": Conflicting lock is held in '
        "/usr/bin/python3 (PID 11827) by user someone-else."
    )
    message = attach_error_message(AttachFailure.LOCKED, Exception(detail))
    assert "PID" not in message
    assert "someone-else" not in message
    assert message == (
        "The database is open for writing by another process. TestGen can only read a DuckDB "
        "database when no other process is writing to it."
    )


def test_a_version_mismatch_message_names_the_versions():
    detail = "Trying to read a database file with version number 65, but we can only read versions between 64 and 64."
    message = attach_error_message(AttachFailure.VERSION_MISMATCH, Exception(detail))
    assert "65" in message
    assert "64" in message


def test_a_duckdb_connection_requires_a_database_file():
    service = DuckdbFlavorService()
    with pytest.raises(ValueError, match="Database File is required."):
        service.validate_parameters({}, "duckdb")
    with pytest.raises(ValueError, match="Database File is required."):
        service.validate_parameters({"database_file": "   "}, "duckdb")
    with pytest.raises(ValueError, match="Database File is required."):
        service.validate_parameters(None, "duckdb")


def test_an_undeclared_parameter_is_rejected_by_name():
    service = DuckdbFlavorService()
    with pytest.raises(ValueError, match="'memory_limit' is not a connection parameter"):
        service.validate_parameters({"database_file": "/data/c.duckdb", "memory_limit": "4GB"}, "duckdb")


def test_a_well_formed_duckdb_parameter_set_validates():
    DuckdbFlavorService().validate_parameters({"database_file": "/data/c.duckdb"}, "duckdb")


def test_a_flavor_that_declares_no_parameters_accepts_none():
    from testgen.common.database.flavor.postgresql_flavor_service import PostgresqlFlavorService

    PostgresqlFlavorService().validate_parameters(None, "postgresql")
    PostgresqlFlavorService().validate_parameters({}, "postgresql")


def test_a_flavor_that_declares_no_parameters_still_rejects_stray_keys():
    from testgen.common.database.flavor.postgresql_flavor_service import PostgresqlFlavorService

    with pytest.raises(ValueError, match="'database_file' is not a connection parameter"):
        PostgresqlFlavorService().validate_parameters({"database_file": "/data/c.duckdb"}, "postgresql")


# Every DuckDB type and every alias its documentation lists, with the general_type the schema
# query must return written into the column-name prefix.
TYPED_COLUMNS = (
    ("a_varchar", "VARCHAR"),
    ("a_varchar_n", "VARCHAR(50)"),
    ("a_char", "CHAR(3)"),
    ("a_bpchar", "BPCHAR(4)"),
    ("a_text", "TEXT"),
    ("a_string", "STRING"),
    ("a_enum", "ENUM('a', 'b')"),
    ("n_tinyint", "TINYINT"),
    ("n_int1", "INT1"),
    ("n_smallint", "SMALLINT"),
    ("n_int2", "INT2"),
    ("n_short", "SHORT"),
    ("n_integer", "INTEGER"),
    ("n_int", "INT"),
    ("n_int4", "INT4"),
    ("n_signed", "SIGNED"),
    ("n_bigint", "BIGINT"),
    ("n_int8", "INT8"),
    ("n_long", "LONG"),
    ("n_hugeint", "HUGEINT"),
    # The unsigned integers and BIGNUM report no numeric_precision, so the precision signal
    # alone would leave them unprofiled.
    ("n_utinyint", "UTINYINT"),
    ("n_usmallint", "USMALLINT"),
    ("n_uinteger", "UINTEGER"),
    ("n_ubigint", "UBIGINT"),
    ("n_uhugeint", "UHUGEINT"),
    ("n_bignum", "BIGNUM"),
    ("n_decimal", "DECIMAL(12,4)"),
    ("n_decimal0", "DECIMAL(10,0)"),
    ("n_numeric", "NUMERIC(4,2)"),
    ("n_float", "FLOAT"),
    ("n_float4", "FLOAT4"),
    ("n_real", "REAL"),
    ("n_double", "DOUBLE"),
    ("n_float8", "FLOAT8"),
    ("d_date", "DATE"),
    ("d_timestamp", "TIMESTAMP"),
    ("d_datetime", "DATETIME"),
    ("d_timestamptz", "TIMESTAMPTZ"),
    ("d_timestamp_with_tz", "TIMESTAMP WITH TIME ZONE"),
    ("d_timestamp_s", "TIMESTAMP_S"),
    ("d_timestamp_ms", "TIMESTAMP_MS"),
    ("d_timestamp_ns", "TIMESTAMP_NS"),
    ("t_time", "TIME"),
    ("t_timetz", "TIMETZ"),
    ("t_time_with_tz", "TIME WITH TIME ZONE"),
    ("t_time_ns", "TIME_NS"),
    ("b_boolean", "BOOLEAN"),
    ("b_bool", "BOOL"),
    ("b_logical", "LOGICAL"),
    ("x_blob", "BLOB"),
    ("x_binary", "BINARY"),
    ("x_bit", "BIT(3)"),
    ("x_uuid", "UUID"),
    ("x_interval", "INTERVAL"),
    ("x_json", "JSON"),
    # A nested type spells out the types it contains, so substring matching would read
    # MAP(VARCHAR, INTEGER) as text and DECIMAL(12,4)[] as a number.
    ("x_list_varchar", "VARCHAR[]"),
    ("x_list_decimal", "DECIMAL(12,4)[]"),
    ("x_array_fixed", "INTEGER[3]"),
    ("x_struct", "STRUCT(y VARCHAR)"),
    ("x_struct_enum", "STRUCT(size ENUM('a', 'b'))"),
    ("x_map", "MAP(VARCHAR, INTEGER)"),
    ("x_union", "UNION(num INTEGER, str VARCHAR)"),
)


@pytest.fixture
def typed_database(tmp_path):
    """A database covering the scalar, nested and parameterized types DuckDB reports."""
    path = tmp_path / "typed.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("CREATE SCHEMA demo")
    columns = ", ".join(f"{name} {type_sql}" for name, type_sql in TYPED_COLUMNS)
    connection.execute(f"CREATE TABLE demo.everything ({columns})")
    connection.execute("INSERT INTO demo.everything (a_varchar) VALUES ('a'), ('b'), ('c')")
    connection.execute("CREATE VIEW demo.a_view AS SELECT a_varchar FROM demo.everything")
    connection.close()
    return path


def read_schema_ddf(database_file) -> dict:
    from testgen.common.read_file import read_template_sql_file

    sql = read_template_sql_file("get_schema_ddf.sql", "flavors/duckdb/data_chars")
    sql = sql.replace("{DATA_SCHEMA}", "demo").replace("{TABLE_CRITERIA}", "")

    service = DuckdbFlavorService()
    params = connection_params(database_file)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            return {
                (row.table_name, row.column_name): row
                for row in connection.execute(text(sql)).mappings().all()
            }
    finally:
        engine.dispose()


def test_schema_discovery_classifies_every_duckdb_type(typed_database):
    rows = read_schema_ddf(typed_database)
    misread = {
        name: (rows[("everything", name)]["db_data_type"], rows[("everything", name)]["general_type"])
        for name, _ in TYPED_COLUMNS
        if rows[("everything", name)]["general_type"] != name[0].upper()
    }
    assert not misread, f"classified against the general_type in the column name: {misread}"


def test_schema_discovery_reports_only_the_attached_database(typed_database):
    """information_schema spans every attached database, and a temp table shares the default
    schema name, so a same-named table elsewhere would be reported as the customer's."""
    from testgen.common.read_file import read_template_sql_file

    sql = read_template_sql_file("get_schema_ddf.sql", "flavors/duckdb/data_chars")
    sql = sql.replace("{DATA_SCHEMA}", "demo").replace("{TABLE_CRITERIA}", "")

    service = DuckdbFlavorService()
    params = connection_params(typed_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS memory.demo"))
            connection.execute(text("CREATE TABLE memory.demo.everything (intruder VARCHAR)"))
            columns = {row.column_name for row in connection.execute(text(sql)).mappings().all()}
    finally:
        engine.dispose()

    assert "intruder" not in columns
    assert "a_varchar" in columns


def test_schema_discovery_reports_type_names_without_quotes(typed_database):
    """Both type columns reach the profiling query inside a single-quoted literal, and an ENUM
    spells its values out."""
    rows = read_schema_ddf(typed_database)
    quoted = {
        column: (row["column_type"], row["db_data_type"])
        for (_, column), row in rows.items()
        if "'" in row["column_type"] or "'" in row["db_data_type"]
    }
    assert not quoted, f"a quote would end the literal early: {quoted}"
    assert rows[("everything", "a_enum")]["db_data_type"] == "ENUM"


def test_schema_discovery_reports_unbounded_strings(typed_database):
    """DuckDB never populates character_maximum_length, so every string column is unbounded."""
    rows = read_schema_ddf(typed_database)
    for column in ("a_varchar", "a_varchar_n", "a_char", "a_bpchar", "a_text", "a_string"):
        assert rows[("everything", column)]["column_type"] == "varchar(65535)"


def test_schema_discovery_reports_decimal_scale(typed_database):
    rows = read_schema_ddf(typed_database)
    assert rows[("everything", "n_decimal")]["column_type"] == "numeric(12,4)"
    assert rows[("everything", "n_decimal")]["is_decimal"] is True
    assert rows[("everything", "n_decimal0")]["is_decimal"] is False


def test_schema_discovery_separates_tables_from_views(typed_database):
    rows = read_schema_ddf(typed_database)
    assert rows[("everything", "a_varchar")]["object_type"] == "TABLE"
    assert rows[("everything", "a_varchar")]["approx_record_ct"] == 3
    assert rows[("a_view", "a_varchar")]["object_type"] == "VIEW"
    # duckdb_views() carries no row estimate.
    assert rows[("a_view", "a_varchar")]["approx_record_ct"] is None


def test_the_attachment_survives_a_rollback(customer_database):
    """ATTACH participates in the transaction, so init() commits it.

    Without that, a rollback drops the catalog and every later query fails on an unresolvable
    name instead of on whatever actually went wrong.
    """
    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            with pytest.raises(SQLAlchemyError):
                connection.execute(text("SELECT * FROM no_such_table"))
            connection.rollback()
            assert connection.execute(text("SELECT count(*) FROM sales.orders")).scalar() == 1
    finally:
        engine.dispose()


def profiling_sql(name, column_type, db_data_type, general_type, *, table="profiled", sampled=False):
    """Render the real profiling query for one column, the way a profiling run would."""
    import datetime
    import uuid
    from types import SimpleNamespace

    from testgen.commands.queries.profiling_query import ProfilingSQL, TableSampling
    from testgen.common.database.column_chars import ColumnChars

    connection_record = SimpleNamespace(sql_flavor="duckdb", sql_flavor_code="duckdb", connection_id=1)
    table_group = SimpleNamespace(
        project_code="DEMO", id=uuid.uuid4(), table_group_schema="sales",
        profile_id_column_mask="%_id", profile_sk_column_mask="%_sk",
    )
    profiling_run = SimpleNamespace(id=uuid.uuid4(), profiling_starttime=datetime.datetime(2026, 9, 8, 12, 0))
    builder = ProfilingSQL(connection_record, table_group, profiling_run)

    column_chars = ColumnChars(
        schema_name="sales", table_name=table, column_name=name, ordinal_position=1,
        column_type=column_type, general_type=general_type, db_data_type=db_data_type,
        record_ct=3, is_decimal=general_type == "N", object_type="TABLE",
    )
    sampling = (
        TableSampling(table_name=table, sample_count=2, sample_ratio=1.5, sample_percent=60.0)
        if sampled else None
    )
    sql, _ = builder.run_column_profiling(column_chars, table_sampling=sampling)
    return sql


def run_profiling_sql(database_file, sql):
    service = DuckdbFlavorService()
    params = connection_params(database_file)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            return connection.execute(text(sql)).mappings().all()
    finally:
        engine.dispose()


@pytest.mark.parametrize("sampled", [False, True], ids=["unsampled", "sampled"])
@pytest.mark.parametrize("general_type", ["A", "N", "D", "B", "X"])
def test_the_profiling_query_runs_for_every_general_type(customer_database, general_type, sampled):
    """The template's per-type branches each have to be valid DuckDB, sampled or not."""
    column_for = {
        "A": ("note", "varchar(65535)", "VARCHAR"),
        "N": ("amount", "numeric(12,4)", "DECIMAL(12,4)"),
        "D": ("placed_at", "timestamp", "TIMESTAMP"),
        "B": ("shipped", "boolean", "BOOLEAN"),
        "X": ("payload", "blob", "BLOB"),
    }
    name, column_type, db_data_type = column_for[general_type]
    sql = profiling_sql(name, column_type, db_data_type, general_type, sampled=sampled)
    run_profiling_sql(customer_database, sql)


@pytest.mark.parametrize(
    ("column", "db_data_type"),
    [
        ("placed_at", "TIMESTAMP"),
        ("placed_at_s", "TIMESTAMP_S"),
        ("placed_at_ms", "TIMESTAMP_MS"),
        # TIMESTAMP_NS cannot represent the min_date floor, so comparing against it raises unless
        # the column is cast first. Arrow and Parquet produce this type by default.
        ("placed_at_ns", "TIMESTAMP_NS"),
        ("placed_at_tz", "TIMESTAMP WITH TIME ZONE"),
        ("placed_on", "DATE"),
    ],
)
def test_every_date_type_profiles(customer_database, column, db_data_type):
    rows = run_profiling_sql(
        customer_database, profiling_sql(column, db_data_type.lower(), db_data_type, "D")
    )
    assert rows[0]["min_date"] is not None


@pytest.mark.parametrize(
    ("column", "db_data_type"),
    [("amount", "DECIMAL(12,4)"), ("unsigned_amount", "UBIGINT"), ("bignum_amount", "VARINT")],
)
def test_every_numeric_type_profiles(customer_database, column, db_data_type):
    """BIGNUM has no cast to FLOAT, and the unsigned integers report no numeric_precision."""
    rows = run_profiling_sql(
        customer_database, profiling_sql(column, db_data_type.lower(), db_data_type, "N")
    )
    assert rows[0]["avg_value"] is not None


def test_small_magnitude_values_are_not_rounded_away(customer_database):
    """A NUMERIC cast resolves to DECIMAL(18,3) in DuckDB, which rounds these to zero.

    Postgres NUMERIC is arbitrary precision, so the cast is harmless there and the template it was
    copied from carries it.
    """
    rows = run_profiling_sql(
        customer_database, profiling_sql("rate", "double", "DOUBLE", "N", table="tiny")
    )
    row = rows[0]
    assert row["zero_value_ct"] == 1, "only one of the five values is actually zero"
    assert float(row["min_value_over_0"]) == pytest.approx(0.0004)
    assert float(row["percentile_50"]) == pytest.approx(0.0004)


# --- Test Connection ---------------------------------------------------------------------


def duckdb_connection(database_file):
    from testgen.common.models.connection import Connection

    return Connection(
        project_code="DEMO",
        connection_id=1,
        connection_name="duck",
        sql_flavor="duckdb",
        sql_flavor_code="duckdb",
        parameters={"database_file": str(database_file)},
        max_threads=4,
        max_query_chars=20000,
    )


def test_a_database_that_attaches_passes_the_connection_test(customer_database):
    from testgen.common.database.connection_service import test_connection_status

    status = test_connection_status(duckdb_connection(customer_database))
    assert status.successful is True
    assert status.details is None


def test_a_missing_file_is_reported_by_the_connection_test(tmp_path):
    from testgen.common.database.connection_service import test_connection_status

    status = test_connection_status(duckdb_connection(tmp_path / "absent.duckdb"))
    assert status.successful is False
    assert status.details == "The database file was not found at this path."


def test_a_file_that_is_not_a_database_is_reported_by_the_connection_test(tmp_path):
    from testgen.common.database.connection_service import test_connection_status

    not_a_database = tmp_path / "notes.duckdb"
    not_a_database.write_text("this is plain text\n")
    status = test_connection_status(duckdb_connection(not_a_database))
    assert status.successful is False
    assert status.details == "This file is not a DuckDB database."


def test_a_recognized_other_format_is_reported_as_not_a_database(tmp_path):
    """DuckDB reports a path whose extension it knows as another format with wording of its own
    ("Cannot launch in-memory database in read-only mode"), which says nothing to the user."""
    from testgen.common.database.connection_service import test_connection_status

    csv_file = tmp_path / "export.csv"
    csv_file.write_text("a,b\n1,2\n")
    status = test_connection_status(duckdb_connection(csv_file))
    assert status.successful is False
    assert status.details == "This file is not a DuckDB database."


def test_a_motherduck_path_is_rejected_before_it_can_open_a_browser(tmp_path):
    """ATTACH on an md: path starts an interactive SSO flow and blocks for a minute."""
    service = DuckdbFlavorService()
    for path in ("md:analytics", "MD:analytics", "motherduck:analytics"):
        with pytest.raises(ValueError, match="MotherDuck"):
            service.validate_parameters({"database_file": path}, "duckdb")


def test_a_local_path_is_accepted():
    DuckdbFlavorService().validate_parameters({"database_file": "/data/warehouse.duckdb"}, "duckdb")


@pytest.mark.parametrize("path", ["s3://bucket/warehouse.duckdb", "https://host/warehouse.duckdb"])
def test_a_remote_path_is_accepted(path):
    """DuckDB attaches these read-only through its bundled extensions."""
    DuckdbFlavorService().validate_parameters({"database_file": path}, "duckdb")


@pytest.mark.parametrize(
    ("sql_flavor_code", "key"),
    [("duckdb", "database_file"), ("files", "base_path")],
)
def test_both_duckdb_codes_accept_the_same_kinds_of_path(sql_flavor_code, key):
    """One flavor accepting a path the other rejects would be a difference with no reason
    behind it, since the same engine opens both."""
    service = DuckdbFlavorService()
    service.validate_parameters({key: "/data/target"}, sql_flavor_code)
    service.validate_parameters({key: "~/data/target"}, sql_flavor_code)
    with pytest.raises(ValueError, match="must be an absolute path"):
        service.validate_parameters({key: "data/target"}, sql_flavor_code)


@pytest.mark.parametrize(
    ("sql_flavor_code", "key", "getter"),
    [
        ("duckdb", "database_file", DuckdbFlavorService.get_database_file),
        ("files", "base_path", DuckdbFlavorService.get_base_path),
    ],
)
def test_a_leading_tilde_is_expanded_before_the_path_is_used(sql_flavor_code, key, getter):
    """DuckDB expands ~ itself, so anything TestGen checks against the path has to see the same
    place the engine opens."""
    params = resolve_connection_params(
        {"sql_flavor": "duckdb", "sql_flavor_code": sql_flavor_code, "parameters": {key: "~/data/target"}}
    )
    resolved = getter(DuckdbFlavorService(), params)
    assert resolved == str(Path.home() / "data/target")
    assert "~" not in resolved


def test_surrounding_whitespace_is_trimmed_from_the_path(customer_database):
    """A pasted path routinely carries it, and it would otherwise read as a missing file."""
    service = DuckdbFlavorService()
    padded = resolve_connection_params(connection_params(f"  {customer_database}  "))
    assert service.get_database_file(padded) == str(customer_database)


def test_a_lock_conflict_is_reported_by_the_connection_test(customer_database, monkeypatch):
    """A writer in another process holds DuckDB's file lock, and the reader cannot open at all."""
    import subprocess
    import sys

    from testgen.common.database.connection_service import test_connection_status
    from testgen.common.database.flavor import duckdb_flavor_service

    # The real attempt count is kept so the retry path is exercised: a failed ATTACH aborts the
    # transaction, and without a rollback the later attempts raise something else entirely and
    # classify as UNKNOWN. Only the backoff is shortened.
    monkeypatch.setattr(duckdb_flavor_service, "_LOCK_RETRY_INITIAL_WAIT_SECONDS", 0.05)

    holder = (
        # The connection has to stay bound, or it is collected and the lock released at once.
        f"import duckdb, time; held = duckdb.connect({str(customer_database)!r}); "
        "print('held', flush=True); time.sleep(30)"
    )
    argv = [sys.executable, "-c", holder]
    writer = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True)  # noqa: S603
    try:
        assert writer.stdout.readline().strip() == "held"
        status = test_connection_status(duckdb_connection(customer_database))
    finally:
        writer.kill()
        writer.wait()

    assert status.successful is False
    assert status.details == (
        "The database is open for writing by another process. TestGen can only read a DuckDB "
        "database when no other process is writing to it."
    )


TEMPLATE_ROOT = Path(__file__).parents[3] / "testgen" / "template"

# A pattern literal that follows the ~ / !~ operator, and the operator itself.
_TILDE_PATTERN = re.compile(r"(!?~)\s*E?'((?:[^']|'')*)'")


def duckdb_flavor_rows():
    """Every duckdb-keyed record in the test type and hygiene issue YAMLs."""

    def walk(node):
        if isinstance(node, dict):
            if node.get("sql_flavor") == "duckdb":
                yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    for directory in ("dbsetup_test_types", "dbsetup_anomaly_types"):
        for path in sorted((TEMPLATE_ROOT / directory).glob("*.yaml")):
            for row in walk(yaml.safe_load(path.read_text())):
                yield path.name, row


def tilde_patterns():
    """Each (source, pattern) pair the duckdb SQL uses with the ~ operator."""
    for path in sorted((TEMPLATE_ROOT / "flavors" / "duckdb").rglob("*")):
        if path.is_file() and path.suffix in (".sql", ".yaml"):
            for _operator, pattern in _TILDE_PATTERN.findall(path.read_text()):
                yield f"flavors/duckdb/{path.name}", pattern

    for file_name, row in duckdb_flavor_rows():
        for key, value in row.items():
            if isinstance(value, str):
                for _operator, pattern in _TILDE_PATTERN.findall(value):
                    yield f"{file_name}:{key}", pattern



def split_top_level_alternatives(pattern: str) -> list[str]:
    """Split on the | characters that sit outside any group or character class."""
    parts, depth, in_class, current = [], 0, False, []
    escaped = False
    for character in pattern:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\":
            current.append(character)
            escaped = True
        elif in_class:
            current.append(character)
            in_class = character != "]"
        elif character == "[":
            current.append(character)
            in_class = True
        elif character == "(":
            depth += 1
            current.append(character)
        elif character == ")":
            depth -= 1
            current.append(character)
        elif character == "|" and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
    parts.append("".join(current))
    return parts


def is_fully_anchored(pattern: str) -> bool:
    """Whether every top-level alternative is anchored at both ends.

    ``^a|b$`` starts with ^ and ends with $ while leaving both alternatives unanchored, so
    checking only the first and last character of the whole pattern is not enough.
    """
    return all(
        alternative.startswith("^") and alternative.endswith("$")
        for alternative in split_top_level_alternatives(pattern)
    )


def test_the_tilde_operator_is_only_used_with_an_anchored_pattern():
    """DuckDB's ~ requires the pattern to match the whole value, where Postgres searches within it.

    A pattern anchored with ^ and $ means the same thing under either reading. An unanchored one
    silently inverts: a positive match finds nothing and a negated one excludes nothing. Those
    belong in regexp_matches, which searches.
    """
    unanchored = [
        (source, pattern)
        for source, pattern in tilde_patterns()
        # A placeholder is resolved to a whole-value pattern at run time.
        if not pattern.startswith("{") and not is_fully_anchored(pattern)
    ]
    assert not unanchored, "Unanchored patterns used with ~: " + "; ".join(
        f"{source} -> {pattern}" for source, pattern in unanchored
    )


def similar_to_patterns():
    """Each (source, pattern) pair the duckdb SQL uses with SIMILAR TO.

    Covers the same two surfaces as ``tilde_patterns`` — the flavor templates and the duckdb-keyed
    YAML records. Scanning only the templates leaves the lookup queries unchecked.
    """
    matcher = re.compile(r"SIMILAR TO\s*'((?:[^']|'')*)'")
    for path in sorted((TEMPLATE_ROOT / "flavors" / "duckdb").rglob("*")):
        if path.is_file() and path.suffix in (".sql", ".yaml"):
            for pattern in matcher.findall(path.read_text()):
                yield f"flavors/duckdb/{path.name}", pattern

    for file_name, row in duckdb_flavor_rows():
        for key, value in row.items():
            if isinstance(value, str):
                for pattern in matcher.findall(value):
                    yield f"{file_name}:{key}", pattern


def test_similar_to_never_carries_an_unescaped_dot():
    """DuckDB reads SIMILAR TO as a regex, where a bare dot matches any character.

    Postgres treats it as a literal, so a pattern copied across unescaped stops discriminating and
    matches every value.
    """
    offending = [
        f"{source} -> {pattern}"
        for source, pattern in similar_to_patterns()
        if re.search(r"(?<!\\)\.", pattern)
    ]
    assert not offending, "Unescaped dot in a SIMILAR TO pattern: " + "; ".join(offending)


def test_similar_to_never_carries_an_anchor():
    """SIMILAR TO is whole-value on both engines, but Postgres matches ^ and $ literally where
    DuckDB honors them. A pattern needing anchors belongs with the ~ operator.
    """
    offending = [
        f"{source} -> {pattern}"
        for source, pattern in similar_to_patterns()
        if "^" in pattern or "$" in pattern
    ]
    assert not offending, "Anchor inside a SIMILAR TO pattern: " + "; ".join(offending)


def test_no_narrowing_type_cast_in_the_duckdb_templates():
    """NUMERIC and FLOAT are narrower in DuckDB than the Postgres types of the same name.

    Postgres NUMERIC is arbitrary precision and its FLOAT is double precision; DuckDB resolves them
    to DECIMAL(18,3) and a 4-byte float. A cast copied across silently loses magnitude or precision.
    """
    narrowing = re.compile(r"(?:::(NUMERIC|FLOAT)\b|\bAS\s+(NUMERIC|FLOAT)\s*\))", re.IGNORECASE)
    offending = []
    for path in sorted((TEMPLATE_ROOT / "flavors" / "duckdb").rglob("*.sql")):
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if narrowing.search(line):
                offending.append(f"{path.name}:{line_number}")
    assert not offending, "Narrowing NUMERIC/FLOAT cast: " + "; ".join(offending)


def _spill_directory_of(connection) -> str:
    return connection.execute(text("SELECT current_setting('temp_directory')")).scalar()


def _aged(path, age) -> None:
    stamp = (datetime.now(UTC) - age - timedelta(minutes=1)).timestamp()
    os.utime(path, (stamp, stamp))


def test_each_connection_spills_to_a_directory_of_its_own(customer_database, spill_root):
    """Spill filenames carry no instance identifier, so two instances sharing a directory
    overwrite each other's files and the process segfaults."""
    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as first, engine.connect() as second:
            service.init(first, resolve_connection_params(params), [])
            service.init(second, resolve_connection_params(params), [])
            assert _spill_directory_of(first) != _spill_directory_of(second)
            assert _spill_directory_of(first).startswith(str(spill_root))
    finally:
        engine.dispose()


def test_a_connection_that_never_spills_leaves_no_directory_behind(customer_database, spill_root):
    """DuckDB creates the directory only when a query spills, so nothing accumulates per run."""
    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            connection.execute(text("SELECT count(*) FROM sales.orders")).scalar()
    finally:
        engine.dispose()

    assert list(spill_root.iterdir()) == []


def test_a_connection_that_spills_and_closes_cleanly_leaves_no_directory_behind(customer_database, spill_root):
    """What decides whether the sweep is a backstop or the only collector. A DuckDB or
    duckdb-engine upgrade that stopped removing the directory on close would turn every spilling
    run into an orphan, and nothing else would notice."""
    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            connection.execute(text("SET memory_limit = '150MB'"))
            connection.execute(text("SET threads = 2"))
            spilled_into = Path(_spill_directory_of(connection))
            connection.execute(
                text("CREATE TEMP TABLE spilled AS SELECT i, repeat(md5(i::VARCHAR), 40) AS pad"
                     " FROM range(1500000) tbl(i)")
            )
            assert any(spilled_into.iterdir()), "the query did not spill, so the test proves nothing"
    finally:
        engine.dispose()

    assert not spilled_into.exists()
    assert list(spill_root.iterdir()) == []


def test_the_spill_directory_survives_the_rollback_the_attach_retry_performs(customer_database, spill_root):
    """``_set_spill_directory`` runs before ``_attach``, whose lock retry rolls back. DuckDB
    settings are not transactional, which is what makes that ordering safe."""
    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            assigned = _spill_directory_of(connection)
            connection.rollback()
            assert _spill_directory_of(connection) == assigned
    finally:
        engine.dispose()


def test_the_sweep_removes_a_directory_a_killed_process_left_behind(spill_root, dead_pid):
    """A clean close takes the directory with it; a SIGKILL does not, and it is never reopened."""
    orphaned = spill_root / f"{dead_pid}-{'a' * 32}"
    orphaned.mkdir(parents=True)
    (orphaned / "duckdb_temp_storage_S32K-0.tmp").write_bytes(b"spill")
    _aged(orphaned, duckdb_flavor_service._STALE_SPILL_AGE)

    recent = spill_root / f"{dead_pid}-{'b' * 32}"
    recent.mkdir()

    duckdb_flavor_service.sweep_stale_spill_directories()

    assert not orphaned.exists()
    assert recent.exists()


def test_the_sweep_spares_a_directory_whose_process_is_still_running(spill_root):
    """DuckDB grows its spill files in place, so a directory's age says when a run first spilled,
    not whether it is still writing. Collecting a live one costs the run its spill files."""
    live = spill_root / f"{os.getpid()}-{'c' * 32}"
    live.mkdir(parents=True)
    _aged(live, duckdb_flavor_service._STALE_SPILL_AGE)

    duckdb_flavor_service.sweep_stale_spill_directories()

    assert live.exists()


def test_the_sweep_ignores_directories_it_did_not_create(spill_root):
    spill_root.mkdir(parents=True)
    stranger = spill_root / "someone-elses-data"
    stranger.mkdir()
    _aged(stranger, duckdb_flavor_service._STALE_SPILL_AGE)

    duckdb_flavor_service.sweep_stale_spill_directories()

    assert stranger.exists()


def test_the_sweep_refuses_to_follow_a_symlinked_root(tmp_path, monkeypatch, dead_pid):
    """The path is predictable and its parent is world-writable on a standalone install."""
    victim = tmp_path / "victim"
    inside = victim / f"{dead_pid}-{'d' * 32}"
    inside.mkdir(parents=True)
    _aged(inside, duckdb_flavor_service._STALE_SPILL_AGE)
    link = tmp_path / "link"
    link.symlink_to(victim, target_is_directory=True)

    monkeypatch.setattr(duckdb_flavor_service, "TEMP_DIRECTORY", link)
    duckdb_flavor_service.sweep_stale_spill_directories()

    assert inside.exists()


def test_opening_a_connection_does_not_sweep(customer_database, spill_root, dead_pid):
    """The sweep walks and deletes directories, so it stays off the path a request waits on."""
    orphaned = spill_root / f"{dead_pid}-{'e' * 32}"
    orphaned.mkdir(parents=True)
    _aged(orphaned, duckdb_flavor_service._STALE_SPILL_AGE)

    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
    finally:
        engine.dispose()

    assert orphaned.exists()


def test_a_directory_name_the_sweep_cannot_parse_stops_neither_it_nor_the_job(spill_root, dead_pid):
    """The pid reaches os.kill, which raises OverflowError on a value too wide for a C int. A
    cleanup that cannot handle one directory must still collect the rest and must not reach the
    job it runs for."""
    spill_root.mkdir(parents=True)
    (spill_root / f"99999999999999-{'a' * 32}").mkdir()
    collectable = spill_root / f"{dead_pid}-{'b' * 32}"
    collectable.mkdir()
    _aged(collectable, duckdb_flavor_service._STALE_SPILL_AGE)

    duckdb_flavor_service.sweep_stale_spill_directories()

    assert not collectable.exists()


def test_the_sweep_matches_a_whole_directory_name(spill_root, dead_pid):
    """A prefix match would reach beyond the names this module creates."""
    spill_root.mkdir(parents=True)
    near_miss = spill_root / f"{dead_pid}-{'c' * 32}-notours"
    near_miss.mkdir()
    _aged(near_miss, duckdb_flavor_service._STALE_SPILL_AGE)

    duckdb_flavor_service.sweep_stale_spill_directories()

    assert near_miss.exists()


def test_the_spill_root_is_not_readable_by_other_accounts(customer_database, spill_root):
    """Spill files are pages of the customer's own rows."""
    service = DuckdbFlavorService()
    params = connection_params(customer_database)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
    finally:
        engine.dispose()

    assert stat.S_IMODE(spill_root.stat().st_mode) == 0o700


# ---------------------------------------------------------------------------
# Files — a connection whose tables are declared file by file
# ---------------------------------------------------------------------------


@pytest.fixture
def data_directory(tmp_path):
    root = tmp_path / "data"
    (root / "nested").mkdir(parents=True)
    (root / "claims_2024.csv").write_text("claim_id,amount\n1,10.5\n2,20.25\n")
    (root / "claims_2025.csv").write_text("claim_id,amount,plan\n3,30.0,gold\n")
    (root / "nested" / "extra.csv").write_text("claim_id,amount\n4,40.0\n")
    (root / "piped.csv").write_text("claim_id|amount\n5|50.0\n")
    duckdb.connect().execute(f"COPY (SELECT 1 AS id, 'x' AS label) TO '{root}/dim.parquet' (FORMAT PARQUET)")
    (root / "notes.json").write_text('{"id": 1, "note": "first"}\n{"id": 2, "note": "second"}\n')
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.csv").write_text("a\n1\n")
    return root


def files_params(base_path) -> dict:
    return {
        "sql_flavor": "duckdb",
        "sql_flavor_code": "files",
        "parameters": {"base_path": str(base_path)},
    }


def open_files_connection(service, params, declarations=()):
    """Open a target connection the way TestGen opens one, declarations and all."""
    engine = service.create_engine(params)
    connection = engine.connect()
    service.init(connection, resolve_connection_params(params), parse_file_declarations(list(declarations)))
    return engine, connection


def test_the_files_code_shares_the_duckdb_family():
    assert FLAVOR_CODE_TO_FAMILY[SqlFlavorCode.FILES] == "duckdb"
    assert str(FLAVOR_CODE_TO_LABEL[SqlFlavorCode.FILES]) == "Local Files"


def test_only_the_files_code_declares_its_tables():
    """Pinning a schema and declaring tables as files are separate facts; a flavor can do the
    first without the second."""
    assert declares_files(SqlFlavorCode.FILES)
    assert fixed_table_group_schema(SqlFlavorCode.FILES) == "main"
    assert not declares_files(SqlFlavorCode.DUCKDB)
    assert fixed_table_group_schema(SqlFlavorCode.DUCKDB) is None
    assert not declares_files(None)


def test_each_duckdb_code_declares_its_own_connection_parameter():
    service = DuckdbFlavorService()
    assert [field.key for field in service.parameters_schema("duckdb")] == ["database_file"]
    assert [field.key for field in service.parameters_schema("files")] == ["base_path"]


def test_a_files_connection_requires_a_base_path():
    with pytest.raises(ValueError, match="Base Path is required."):
        DuckdbFlavorService().validate_parameters({}, "files")


def test_a_relative_base_path_is_rejected():
    """It would resolve against the working directory, which differs between the UI and scheduler."""
    with pytest.raises(ValueError, match="Base Path must be an absolute path."):
        DuckdbFlavorService().validate_parameters({"base_path": "data/claims"}, "files")


def test_an_absolute_base_path_is_accepted():
    DuckdbFlavorService().validate_parameters({"base_path": "/data/claims"}, "files")


def test_a_missing_base_path_is_reported(tmp_path):
    service = DuckdbFlavorService()
    params = files_params(tmp_path / "absent")
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            with pytest.raises(DuckdbConnectionError, match="The base path was not found."):
                service.init(connection, resolve_connection_params(params), [])
    finally:
        engine.dispose()


def test_reads_are_confined_to_the_base_path(data_directory):
    """The allow-list has to be applied before external access is closed, and enforces nothing
    on its own. Either half missing lets this read succeed."""
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory))
    outside = data_directory.parent / "outside" / "secret.csv"
    try:
        with pytest.raises(SQLAlchemyError, match="Permission Error"):
            connection.execute(text(f"SELECT * FROM read_csv('{outside}')")).fetchall()
    finally:
        connection.close()
        engine.dispose()


def test_the_allow_list_is_set_before_external_access_is_closed():
    class Recorder:
        def __init__(self):
            self.statements = []

        def execute(self, clause):
            self.statements.append(str(clause))

        def commit(self):
            pass

    recorder = Recorder()
    DuckdbFlavorService()._confine_reads(recorder, "/data/claims")

    assert recorder.statements == [
        "SET allowed_directories = ['/data/claims']",
        "SET enable_external_access = false",
        "SET lock_configuration = true",
    ]


def test_a_quote_in_the_base_path_cannot_end_the_allow_list_literal():
    class Recorder:
        def __init__(self):
            self.statements = []

        def execute(self, clause):
            self.statements.append(str(clause))

        def commit(self):
            pass

    recorder = Recorder()
    DuckdbFlavorService()._confine_reads(recorder, "/da'ta")
    assert recorder.statements[0] == "SET allowed_directories = ['/da''ta']"


def test_every_declared_format_becomes_a_table(data_directory):
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
        {"name": "dim", "uri": "dim.parquet", "format": "parquet"},
        {"name": "notes", "uri": "notes.json", "format": "json"},
    ])
    try:
        assert connection.execute(text('SELECT COUNT(*) FROM "main"."claims"')).scalar() == 3
        assert connection.execute(text('SELECT COUNT(*) FROM "main"."dim"')).scalar() == 1
        assert connection.execute(text('SELECT COUNT(*) FROM "main"."notes"')).scalar() == 2
    finally:
        connection.close()
        engine.dispose()


def test_a_glob_is_one_table_spanning_every_matching_file(data_directory):
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
    ])
    try:
        assert connection.execute(text('SELECT COUNT(*) FROM "main"."claims"')).scalar() == 3
        # The column only the later file carries survives the union.
        assert connection.execute(text('SELECT COUNT(plan) FROM "main"."claims"')).scalar() == 1
    finally:
        connection.close()
        engine.dispose()


def test_a_recursive_pattern_is_one_table_spanning_the_files_beneath_it(data_directory):
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "everything", "uri": "**/*.csv", "format": "csv"},
    ])
    try:
        # Three claims rows, one nested row, one piped row read as a single column.
        assert connection.execute(text('SELECT COUNT(*) FROM "main"."everything"')).scalar() == 5
    finally:
        connection.close()
        engine.dispose()


def test_a_stored_folder_declaration_reports_why_it_is_not_read(data_directory):
    """A declaration saved another way can still name a folder, which DuckDB would refuse with a
    permission error that says nothing about what to do instead."""
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "nested", "uri": "nested", "format": "csv"},
    ])
    try:
        assert service.declaration_failures(connection) == {"nested": URI_IS_FOLDER}
    finally:
        connection.close()
        engine.dispose()


def test_declared_csv_settings_are_applied(data_directory):
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "piped", "uri": "piped.csv", "format": "csv", "options": {"delimiter": "|"}},
    ])
    try:
        columns = connection.execute(text(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'piped' ORDER BY ordinal_position"
        )).scalars().all()
        assert columns == ["claim_id", "amount"]
    finally:
        connection.close()
        engine.dispose()


def test_one_unreadable_declaration_does_not_take_the_others_with_it(data_directory):
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "missing", "uri": "absent_*.csv", "format": "csv"},
        {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
        {"name": "dim", "uri": "dim.parquet", "format": "parquet"},
    ])
    try:
        built = connection.execute(text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_catalog = current_database() AND table_schema = 'main' ORDER BY table_name"
        )).scalars().all()
        assert built == ["claims", "dim"]
    finally:
        connection.close()
        engine.dispose()


def test_a_failure_reports_the_declaration_it_belongs_to(data_directory):
    service = DuckdbFlavorService()
    params = files_params(data_directory)
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            service.init(connection, resolve_connection_params(params), [])
            failures = service.build_declaration_views(
                connection,
                str(data_directory),
                parse_file_declarations([
                    {"name": "missing", "uri": "absent_*.csv", "format": "csv"},
                    {"name": "escape", "uri": "../outside/secret.csv", "format": "csv"},
                    {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
                ]),
                "main",
            )
    finally:
        engine.dispose()

    assert set(failures) == {"missing", "escape"}
    assert "outside the connection base path" in failures["escape"]


def test_a_name_differing_only_in_case_fails_rather_than_replacing(data_directory):
    """DuckDB folds identifiers even when quoted, so ``Claims`` and ``claims`` are one view."""
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
        {"name": "Claims", "uri": "dim.parquet", "format": "parquet"},
    ])
    try:
        assert set(service.declaration_failures(connection)) == {"Claims"}
        assert connection.execute(text("SELECT count(*) FROM claims")).scalar() == 3
    finally:
        connection.close()
        engine.dispose()


def test_a_name_carrying_sql_never_runs_it(data_directory):
    """The declaration name reaches DDL as an identifier, and duckdb-engine runs every statement
    in one call, so a quote in the name would otherwise be arbitrary SQL against the target."""
    target = data_directory / "claims_2024.csv"
    before = target.read_text()
    injected = (
        f"claims\" AS SELECT 1; COPY (SELECT 99 AS id) TO '{target}' (FORMAT CSV); CREATE VIEW \"junk"
    )

    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": injected, "uri": "claims_*.csv", "format": "csv"},
        {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
    ])
    try:
        built = connection.execute(text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_catalog = current_database() AND table_schema = 'main' ORDER BY table_name"
        )).scalars().all()
        assert built == ["claims"]
        assert service.declaration_failures(connection)[injected] == NAME_INVALID
    finally:
        connection.close()
        engine.dispose()

    assert target.read_text() == before


def test_a_run_opens_a_connection_whose_declarations_did_not_all_build(data_directory, monkeypatch):
    """A declaration that did not build is simply absent from the catalog, which is what a table
    dropped at the source looks like on every other flavor."""
    from testgen.common.database import database_service

    target = database_service.TargetDbParams(files_params(data_directory), parse_file_declarations([
        {"name": "missing", "uri": "absent_*.csv", "format": "csv"},
        {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
    ]))
    monkeypatch.setattr(database_service, "target_db_params", target)
    monkeypatch.setattr(database_service.engine_cache, "target_db", None, raising=False)

    connection = database_service._init_target_db_connection()
    try:
        built = connection.execute(text(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_catalog = current_database() AND table_schema = 'main'"
        )).scalars().all()
        assert built == ["claims"]
    finally:
        connection.close()


def test_the_failures_stay_on_the_connection_for_the_caller(data_directory):
    service = DuckdbFlavorService()
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "missing", "uri": "absent_*.csv", "format": "csv"},
        {"name": "claims", "uri": "claims_*.csv", "format": "csv"},
    ])
    try:
        assert set(service.declaration_failures(connection)) == {"missing"}
    finally:
        connection.close()
        engine.dispose()


def test_a_declaration_outside_the_base_path_never_reaches_sql(data_directory):
    """The allow-list refuses the read too; this keeps the path out of the view's SQL as well,
    and covers the flavors that have no allow-list."""
    service = DuckdbFlavorService()
    outside = data_directory.parent / "outside" / "secret.csv"
    engine, connection = open_files_connection(service, files_params(data_directory), [
        {"name": "escape", "uri": str(outside), "format": "csv"},
    ])
    try:
        built = connection.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables"
            " WHERE table_catalog = current_database() AND table_schema = 'main'"
        )).scalar()
        assert built == 0
    finally:
        connection.close()
        engine.dispose()


def test_a_files_connection_reports_what_it_found(data_directory):
    details = DuckdbFlavorService().test_connection_details(
        resolve_connection_params(files_params(data_directory))
    )
    assert details == "6 files found under the base path."


def test_an_empty_directory_reports_no_count(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    details = DuckdbFlavorService().test_connection_details(resolve_connection_params(files_params(empty)))
    assert details == "No files found under the base path."


def test_a_single_file_is_reported_in_the_singular(tmp_path):
    root = tmp_path / "one"
    root.mkdir()
    (root / "only.csv").write_text("a\n1\n")
    details = DuckdbFlavorService().test_connection_details(resolve_connection_params(files_params(root)))
    assert details == "1 file found under the base path."


def test_a_database_connection_reports_no_file_count(customer_database):
    assert DuckdbFlavorService().test_connection_details(
        resolve_connection_params(connection_params(customer_database))
    ) is None


# -- one database per engine on the files code --------------------------------


def test_the_files_code_keeps_one_database_for_the_engine():
    from sqlalchemy.pool import NullPool, QueuePool

    service = DuckdbFlavorService()
    files = service.get_engine_args(resolve_connection_params(files_params("/data")))
    attached = service.get_engine_args(
        resolve_connection_params({"sql_flavor": "duckdb", "sql_flavor_code": "duckdb",
                                   "parameters": {"database_file": "/data/x.duckdb"}})
    )
    assert files["poolclass"] is QueuePool
    assert (files["pool_size"], files["max_overflow"]) == (1, 0)
    # A read-only ATTACH held for the engine's lifetime locks the file against the customer's
    # own writer, so the attached-file path takes a database per checkout instead.
    assert attached["poolclass"] is NullPool


def test_the_declaration_views_outlive_the_checkout(data_directory):
    """The engine hands out one database, so a later checkout finds the views already built."""
    from testgen.common.database.database_service import initialize_connection

    service = DuckdbFlavorService()
    params = files_params(data_directory)
    declarations = parse_file_declarations([{"name": "claims", "uri": "claims_*.csv", "format": "csv"}])
    resolved = resolve_connection_params(params)
    engine = service.create_engine(params)
    try:
        with engine.connect() as first:
            initialize_connection(service, first, resolved, declarations)
            assert first.execute(text('SELECT COUNT(*) FROM main."claims"')).scalar()

        with engine.connect() as second:
            # Re-running init would raise: the configuration is locked on this database and
            # `SET allowed_directories` is refused once it is.
            initialize_connection(service, second, resolved, declarations)
            assert second.execute(text('SELECT COUNT(*) FROM main."claims"')).scalar()
            assert service.declaration_failures(second) == {}
    finally:
        engine.dispose()


def test_the_attached_database_is_initialized_on_every_checkout(customer_database):
    """Each checkout is its own database on the attached-file path, so each one attaches."""
    from testgen.common.database.database_service import initialize_connection

    service = DuckdbFlavorService()
    params = {"sql_flavor": "duckdb", "sql_flavor_code": "duckdb",
              "parameters": {"database_file": str(customer_database)}}
    resolved = resolve_connection_params(params)
    engine = service.create_engine(params)
    try:
        for _ in range(2):
            with engine.connect() as connection:
                initialize_connection(service, connection, resolved, [])
                assert connection.execute(text("SELECT 1")).scalar() == 1
    finally:
        engine.dispose()


def test_a_failed_init_leaves_the_pool_usable(tmp_path, monkeypatch):
    """The files code pools one connection, so one dropped here would be the whole engine.

    The second attempt has to report what actually went wrong rather than waiting out the pool.
    """
    from testgen.common.database import database_service

    target = database_service.TargetDbParams(files_params(tmp_path / "absent"), [])
    monkeypatch.setattr(database_service, "target_db_params", target)
    monkeypatch.setattr(database_service.engine_cache, "target_db", None, raising=False)

    for _ in range(2):
        with pytest.raises(DuckdbConnectionError, match="base path was not found"):
            database_service._init_target_db_connection()

    assert database_service.engine_cache.target_db.pool.checkedout() == 0
