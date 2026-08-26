"""Tests for ``run_refresh_data_chars``.

Covers ``write_data_chars``'s staging key and its empty-input guard.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from testgen.commands.run_refresh_data_chars import write_data_chars
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
