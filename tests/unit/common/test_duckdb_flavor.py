import re
from pathlib import Path

import duckdb
import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from testgen.common.database.flavor.duckdb_flavor_service import (
    ATTACHED_CATALOG,
    AttachFailure,
    DuckdbConnectionError,
    DuckdbFlavorService,
    attach_error_message,
    classify_attach_error,
)
from testgen.common.database.flavor.flavor_service import resolve_connection_params
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, FLAVOR_CODE_TO_LABEL, SqlFlavorCode


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
            service.init(connection, resolve_connection_params(params))
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
            service.init(connection, resolve_connection_params(params))
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
                service.init(connection, resolve_connection_params(params))
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
                service.init(connection, resolve_connection_params(params))
    finally:
        engine.dispose()


def test_a_missing_file_is_reported_as_missing(tmp_path):
    service = DuckdbFlavorService()
    params = connection_params(tmp_path / "absent.duckdb")
    engine = service.create_engine(params)
    try:
        with engine.connect() as connection:
            with pytest.raises(DuckdbConnectionError) as caught:
                service.init(connection, resolve_connection_params(params))
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
        service.validate_parameters({})
    with pytest.raises(ValueError, match="Database File is required."):
        service.validate_parameters({"database_file": "   "})
    with pytest.raises(ValueError, match="Database File is required."):
        service.validate_parameters(None)


def test_an_undeclared_parameter_is_rejected_by_name():
    service = DuckdbFlavorService()
    with pytest.raises(ValueError, match="'memory_limit' is not a connection parameter"):
        service.validate_parameters({"database_file": "/data/c.duckdb", "memory_limit": "4GB"})


def test_a_well_formed_duckdb_parameter_set_validates():
    DuckdbFlavorService().validate_parameters({"database_file": "/data/c.duckdb"})


def test_a_flavor_that_declares_no_parameters_accepts_none():
    from testgen.common.database.flavor.postgresql_flavor_service import PostgresqlFlavorService

    PostgresqlFlavorService().validate_parameters(None)
    PostgresqlFlavorService().validate_parameters({})


def test_a_flavor_that_declares_no_parameters_still_rejects_stray_keys():
    from testgen.common.database.flavor.postgresql_flavor_service import PostgresqlFlavorService

    with pytest.raises(ValueError, match="'database_file' is not a connection parameter"):
        PostgresqlFlavorService().validate_parameters({"database_file": "/data/c.duckdb"})


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
            service.init(connection, resolve_connection_params(params))
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
            service.init(connection, resolve_connection_params(params))
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
            service.init(connection, resolve_connection_params(params))
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
            service.init(connection, resolve_connection_params(params))
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
            service.validate_parameters({"database_file": path})


def test_a_local_path_is_accepted():
    DuckdbFlavorService().validate_parameters({"database_file": "/data/warehouse.duckdb"})


@pytest.mark.parametrize("path", ["s3://bucket/warehouse.duckdb", "https://host/warehouse.duckdb"])
def test_a_remote_path_is_accepted(path):
    """DuckDB attaches these read-only through its bundled extensions."""
    DuckdbFlavorService().validate_parameters({"database_file": path})


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
