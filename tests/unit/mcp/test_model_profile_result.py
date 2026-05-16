from unittest.mock import MagicMock, patch
from uuid import uuid4

from testgen.common.models.profile_result import ProfileResult


@patch("testgen.common.models.profile_result.ProfileResult.select_where")
@patch("testgen.common.models.data_column.DataColumnChars.select_where")
def test_get_for_column_returns_row_when_run_pinned(dcc_select, pr_select):
    pinned_run_id = uuid4()
    profile = MagicMock(spec=ProfileResult)
    pr_select.return_value = [profile]

    result = ProfileResult.get_for_column(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="email",
        profiling_run_id=pinned_run_id,
    )

    assert result is profile
    # When a profile run is explicitly pinned, we should not fall back to data_column_chars.
    dcc_select.assert_not_called()


@patch("testgen.common.models.profile_result.ProfileResult.select_where")
@patch("testgen.common.models.data_column.DataColumnChars.select_where")
def test_get_for_column_resolves_latest_run_when_unpinned(dcc_select, pr_select):
    latest_run_id = uuid4()
    column = MagicMock()
    column.last_complete_profile_run_id = latest_run_id
    dcc_select.return_value = [column]
    profile = MagicMock(spec=ProfileResult)
    pr_select.return_value = [profile]

    result = ProfileResult.get_for_column(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="email",
    )

    assert result is profile
    dcc_select.assert_called_once()


@patch("testgen.common.models.profile_result.ProfileResult.select_where")
@patch("testgen.common.models.data_column.DataColumnChars.select_where")
def test_get_for_column_returns_none_when_column_unknown(dcc_select, pr_select):
    dcc_select.return_value = []

    result = ProfileResult.get_for_column(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="ghost",
    )

    assert result is None
    pr_select.assert_not_called()


@patch("testgen.common.models.profile_result.ProfileResult.select_where")
@patch("testgen.common.models.data_column.DataColumnChars.select_where")
def test_get_for_column_returns_none_when_column_never_profiled(dcc_select, pr_select):
    column = MagicMock()
    column.last_complete_profile_run_id = None
    dcc_select.return_value = [column]

    result = ProfileResult.get_for_column(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="email",
    )

    assert result is None
    pr_select.assert_not_called()


@patch("testgen.common.models.profile_result.ProfileResult.select_where")
@patch("testgen.common.models.data_column.DataColumnChars.select_where")
def test_get_for_column_returns_none_when_pinned_run_has_no_row(dcc_select, pr_select):
    pr_select.return_value = []

    result = ProfileResult.get_for_column(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="email",
        profiling_run_id=uuid4(),
    )

    assert result is None
