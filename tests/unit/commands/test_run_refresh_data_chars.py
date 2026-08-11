"""Tests for ``run_refresh_data_chars``.

Covers ``write_data_chars``'s empty-input guard.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from testgen.commands.run_refresh_data_chars import write_data_chars

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_refresh_data_chars"


@patch(f"{MODULE}.execute_db_queries")
@patch(f"{MODULE}.write_to_app_db")
def test_write_data_chars_empty_input_touches_nothing(mock_write, mock_execute):
    """Empty input must not reach the refresh SQL.

    ``data_chars_update.sql`` marks as dropped every row of the table group that
    the staging table doesn't account for. Staging nothing therefore reads as
    "every table and column disappeared", which would set ``drop_date`` across
    the whole group and log a 'D' row for each.
    """
    sql_generator = MagicMock()
    sql_generator.get_staging_data_chars.return_value = []

    write_data_chars([], sql_generator, datetime.now(UTC))

    mock_write.assert_not_called()
    mock_execute.assert_not_called()
    sql_generator.update_data_chars.assert_not_called()


@patch(f"{MODULE}.execute_db_queries")
@patch(f"{MODULE}.write_to_app_db")
def test_write_data_chars_stages_then_refreshes(mock_write, mock_execute):
    sql_generator = MagicMock()
    staged = [["row"]]
    sql_generator.get_staging_data_chars.return_value = staged
    sql_generator.staging_columns = ["table_groups_id"]
    sql_generator.staging_table = "stg_data_chars_updates"
    run_date = datetime.now(UTC)

    write_data_chars([MagicMock()], sql_generator, run_date)

    mock_write.assert_called_once_with(staged, ["table_groups_id"], "stg_data_chars_updates")
    sql_generator.update_data_chars.assert_called_once_with(run_date)
    mock_execute.assert_called_once_with(sql_generator.update_data_chars.return_value)
