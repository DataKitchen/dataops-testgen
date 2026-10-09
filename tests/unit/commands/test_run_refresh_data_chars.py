"""Tests for ``run_refresh_data_chars``.

Covers ``write_data_chars``'s staging key and its empty-input guard, and that the scanned
schema reaches the query builder.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch
from uuid import UUID

import pytest

from testgen.commands.run_refresh_data_chars import run_data_chars_refresh, write_data_chars
from testgen.common.database.column_chars import ObjectType
from testgen.common.flavors import SqlFlavorCode
from testgen.common.read_file import read_template_sql_file

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_refresh_data_chars"


@patch(f"{MODULE}.execute_db_queries")
@patch(f"{MODULE}.write_to_app_db")
def test_write_data_chars_stages_then_refreshes(mock_write, mock_execute):
    sql_generator = MagicMock()
    staged = [["row"]]
    sql_generator.get_staging_data_chars.return_value = staged
    sql_generator.staging_columns = ["refresh_id"]
    sql_generator.staging_table = "stg_data_chars_updates"
    run_date = datetime.now(UTC)

    write_data_chars([MagicMock()], sql_generator, run_date)

    mock_write.assert_called_once_with(staged, ["refresh_id"], "stg_data_chars_updates")
    (_, _, refresh_id) = sql_generator.get_staging_data_chars.call_args.args
    sql_generator.update_data_chars.assert_called_once_with(run_date, refresh_id)
    mock_execute.assert_called_once_with(sql_generator.update_data_chars.return_value)


@patch(f"{MODULE}.execute_db_queries")
@patch(f"{MODULE}.write_to_app_db")
def test_write_data_chars_empty_input_touches_nothing(mock_write, mock_execute):
    """Empty input must not reach the refresh SQL.

    ``data_chars_update.sql`` marks as dropped every row of the table group that the
    staging table doesn't account for. An empty scan of the source is not evidence that
    the source is empty — a renamed schema or a revoked grant returns no rows from the
    privilege-filtered metadata views just as silently — so reconciling against nothing
    would set ``drop_date`` across the whole group and log a 'D' row for each.
    """
    sql_generator = MagicMock()
    sql_generator.get_staging_data_chars.return_value = []

    write_data_chars([], sql_generator, datetime.now(UTC))

    mock_write.assert_not_called()
    mock_execute.assert_not_called()
    sql_generator.update_data_chars.assert_not_called()


@patch(f"{MODULE}.execute_db_queries")
@patch(f"{MODULE}.write_to_app_db")
def test_write_data_chars_uses_a_fresh_key_per_call(mock_write, mock_execute):
    """Two refreshes of one table group must not share a staging key.

    A run-date key is truncated to whole seconds, so two refreshes starting in the same
    second would share it: each would read the other's staged rows and each would delete
    them, and the drop passes reconcile an empty scan as every table and column having
    disappeared.
    """
    sql_generator = MagicMock()
    sql_generator.get_staging_data_chars.return_value = [["row"]]
    run_date = datetime.now(UTC)

    write_data_chars([MagicMock()], sql_generator, run_date)
    write_data_chars([MagicMock()], sql_generator, run_date)

    keys = [call.args[2] for call in sql_generator.get_staging_data_chars.call_args_list]
    assert all(isinstance(key, UUID) for key in keys)
    assert keys[0] != keys[1]


# --- The templates are keyed on the refresh, not on the run date ---


@pytest.mark.parametrize("template_name", ["data_chars_update.sql", "data_chars_staging_delete.sql"])
def test_data_chars_templates_key_staging_on_the_refresh(template_name):
    """A run-date predicate here is shared by every refresh that starts in the same second,
    which lets one refresh read and delete another's staged rows."""
    sql = read_template_sql_file(template_name, "data_chars")

    assert "refresh_id = :REFRESH_ID" in sql
    assert "run_date = :RUN_DATE" not in sql


def test_data_chars_update_keys_every_staging_scan():
    """Every scan of the staging table must carry the key — one left unscoped reads the
    other refresh's rows into this refresh's reconciliation."""
    sql = read_template_sql_file("data_chars_update.sql", "data_chars")

    scans = sql.count("FROM stg_data_chars_updates")
    assert scans == 6
    assert sql.count("refresh_id = :REFRESH_ID") == scans


def test_data_chars_drop_passes_refuse_an_empty_scan():
    """Both drop passes mark as dropped everything the scan does not account for, so an
    empty scan would drop the table group's entire catalog."""
    sql = read_template_sql_file("data_chars_update.sql", "data_chars")

    assert sql.count("EXISTS (SELECT 1 FROM new_chars)") == 2


@pytest.mark.parametrize(
    "template_name", ["update_predicted_test_thresholds.sql", "delete_staging_test_definitions.sql"],
)
def test_prediction_templates_key_staging_on_the_test_run(template_name):
    """Same collision as the data characteristics staging: two runs of one test suite starting
    in the same second would share a run-date key."""
    sql = read_template_sql_file(template_name, "prediction")

    assert "test_run_id = :TEST_RUN_ID" in sql
    assert "run_date = :RUN_DATE" not in sql


# --- A refresh on a Files connection ---


def _file_refresh_generator() -> MagicMock:
    sql_generator = MagicMock()
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.flavor_service.caches_tables.return_value = False
    sql_generator.get_schema_ddf.return_value = ("schema query", {})
    sql_generator.get_file_counts.return_value = [("file counts query", None)]
    sql_generator.get_row_counts.return_value = []
    return sql_generator


def _connection(sql_flavor_code: SqlFlavorCode = SqlFlavorCode.FILES) -> MagicMock:
    return MagicMock(effective_max_threads=1, sql_flavor_code=sql_flavor_code)


SCHEMA_ROWS = [
    {"schema_name": "main", "table_name": "claims", "column_name": "id"},
    {"schema_name": "main", "table_name": "claims", "column_name": "amount"},
    {"schema_name": "main", "table_name": "orders", "column_name": "id"},
]


ROW_COUNTS = ([], [], {})


@patch(f"{MODULE}.write_data_chars")
@patch(f"{MODULE}.fetch_from_db_threaded")
@patch(f"{MODULE}.fetch_dict_from_db", return_value=SCHEMA_ROWS)
@patch(f"{MODULE}.RefreshDataCharsSQL")
def test_a_refresh_records_each_file_table(mock_sql, _fetch, mock_threaded, mock_write):
    mock_sql.return_value = _file_refresh_generator()
    file_counts = [{"table_name": "claims", "file_ct": 3}, {"table_name": "orders", "file_ct": 1}]
    mock_threaded.side_effect = [ROW_COUNTS, (file_counts, [], {})]

    data_chars = run_data_chars_refresh(_connection(), MagicMock(), datetime.now(UTC))

    assert [(c.table_name, c.object_type, c.file_ct) for c in data_chars] == [
        ("claims", ObjectType.FILES, 3),
        ("claims", ObjectType.FILES, 3),
        ("orders", ObjectType.FILES, 1),
    ]
    mock_write.assert_called_once()


@patch(f"{MODULE}.write_data_chars")
@patch(f"{MODULE}.fetch_from_db_threaded")
@patch(f"{MODULE}.fetch_dict_from_db", return_value=SCHEMA_ROWS)
@patch(f"{MODULE}.RefreshDataCharsSQL")
def test_a_failed_file_count_does_not_stop_the_refresh(mock_sql, _fetch, mock_threaded, mock_write, caplog):
    mock_sql.return_value = _file_refresh_generator()
    mock_threaded.side_effect = [ROW_COUNTS, ([], [], {0: "glob failed"})]

    data_chars = run_data_chars_refresh(_connection(), MagicMock(), datetime.now(UTC))

    # The object type does not depend on the count, so it is still recorded.
    assert {(c.object_type, c.file_ct) for c in data_chars} == {(ObjectType.FILES, None)}
    mock_write.assert_called_once()
    assert "Could not count files for table group. glob failed" in caplog.text


@patch(f"{MODULE}.write_data_chars")
@patch(f"{MODULE}.fetch_from_db_threaded", return_value=ROW_COUNTS)
@patch(f"{MODULE}.fetch_dict_from_db", return_value=SCHEMA_ROWS)
@patch(f"{MODULE}.RefreshDataCharsSQL")
def test_a_catalog_refresh_records_no_file_counts(mock_sql, _fetch, mock_threaded, mock_write):
    mock_sql.return_value = sql_generator = _file_refresh_generator()

    data_chars = run_data_chars_refresh(_connection(SqlFlavorCode.POSTGRESQL), MagicMock(), datetime.now(UTC))

    assert {(c.object_type, c.file_ct) for c in data_chars} == {(None, None)}
    sql_generator.get_file_counts.assert_not_called()
    mock_threaded.assert_called_once()


# --- the scanned schema ---


@patch(f"{MODULE}.resolve_connection_params", return_value={})
@patch(f"{MODULE}.RefreshDataCharsSQL")
def test_metadata_via_api_flavors_scan_the_table_group_s_schema(mock_sql_cls, _mock_params):
    """Flavors with no information_schema take the schema as an argument rather than through a
    template, so they read it off the table group."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = True
    sql_generator.flavor_service.get_schema_columns.return_value = []
    sql_generator.filter_schema_columns.return_value = []

    run_data_chars_refresh(MagicMock(), MagicMock(table_group_schema="onboard_2026_09_10"), datetime.now(UTC))

    assert sql_generator.flavor_service.get_schema_columns.call_args.args[1] == "onboard_2026_09_10"


@patch(f"{MODULE}.write_data_chars")
@patch(f"{MODULE}.cache_target_tables")
@patch(f"{MODULE}.fetch_from_db_threaded")
@patch(f"{MODULE}.fetch_dict_from_db", return_value=SCHEMA_ROWS)
@patch(f"{MODULE}.RefreshDataCharsSQL")
def test_a_caching_connection_copies_its_tables_before_counting_them(
    mock_sql, _fetch, mock_threaded, mock_cache, _write
):
    mock_sql.return_value = sql_generator = _file_refresh_generator()
    sql_generator.flavor_service.caches_tables.return_value = True
    order = MagicMock()
    mock_cache.side_effect = lambda tables: order.cache(set(tables))
    mock_threaded.side_effect = lambda *_args, **_kwargs: (order.count(), ROW_COUNTS)[1]

    run_data_chars_refresh(_connection(SqlFlavorCode.S3), MagicMock(), datetime.now(UTC))

    assert order.mock_calls[0] == call.cache({"claims", "orders"})
    assert order.mock_calls[1] == call.count()


@patch(f"{MODULE}.write_data_chars")
@patch(f"{MODULE}.cache_target_tables")
@patch(f"{MODULE}.fetch_from_db_threaded", return_value=ROW_COUNTS)
@patch(f"{MODULE}.fetch_dict_from_db", return_value=SCHEMA_ROWS)
@patch(f"{MODULE}.RefreshDataCharsSQL")
def test_a_connection_that_reads_in_place_copies_nothing(mock_sql, _fetch, _threaded, mock_cache, _write):
    mock_sql.return_value = _file_refresh_generator()

    run_data_chars_refresh(_connection(), MagicMock(), datetime.now(UTC))

    mock_cache.assert_not_called()
