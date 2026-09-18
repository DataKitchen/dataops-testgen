from decimal import Decimal
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


# --- ProfileResult.scale_sampled_estimates ---

SCALED_COUNTS = (
    "record_ct",
    "value_ct",
    "null_value_ct",
    "zero_value_ct",
    "lead_space_ct",
    "embedded_space_ct",
    "includes_digit_ct",
    "filled_value_ct",
    "numeric_ct",
    "date_ct",
    "before_1yr_date_ct",
    "before_5yr_date_ct",
    "before_20yr_date_ct",
    "within_1yr_date_ct",
    "within_1mo_date_ct",
    "future_date_ct",
    "boolean_true_ct",
)


def test_scales_exactly_the_counts_the_estimates_update_scaled():
    assert ProfileResult._sampled_estimate_columns == SCALED_COUNTS


def test_every_scaled_count_is_multiplied_by_the_ratio_and_rounded():
    row = dict.fromkeys(SCALED_COUNTS, 2999)
    ProfileResult.scale_sampled_estimates(row, 10000 / 3000)
    assert all(row[column] == 9997 for column in SCALED_COUNTS)
    assert all(isinstance(row[column], int) for column in SCALED_COUNTS)


def test_distinct_counts_and_unscaled_measures_are_left_as_measured():
    row = {
        "record_ct": 300,
        "distinct_value_ct": 280,
        "distinct_std_value_ct": 270,
        "distinct_pattern_ct": 12,
        "zero_length_ct": 3,
        "upper_case_ct": 4,
        "min_value": 1.5,
        "std_pattern_match": "EMAIL",
    }
    ProfileResult.scale_sampled_estimates(row, 10.0)
    assert row["record_ct"] == 3000
    assert {k: v for k, v in row.items() if k not in ("record_ct", "sample_ratio")} == {
        "distinct_value_ct": 280,
        "distinct_std_value_ct": 270,
        "distinct_pattern_ct": 12,
        "zero_length_ct": 3,
        "upper_case_ct": 4,
        "min_value": 1.5,
        "std_pattern_match": "EMAIL",
    }


def test_the_ratio_is_written_onto_the_row():
    row = {"record_ct": 300}
    ProfileResult.scale_sampled_estimates(row, 10000 / 3000)
    assert row["sample_ratio"] == 10000 / 3000


def test_ties_round_away_from_zero_as_the_database_did():
    row = {"record_ct": 1, "value_ct": 3}
    ProfileResult.scale_sampled_estimates(row, 2.5)
    assert row["record_ct"] == 3  # 2.5 -> 3, not banker's 2
    assert row["value_ct"] == 8  # 7.5 -> 8


def test_the_ratio_is_applied_as_written_not_as_a_binary_float():
    # 10 * 1.15 is 11.499999999999998 in binary floating point but 11.5 in the decimal arithmetic
    # the database applied to the literal, which rounds to 12.
    row = {"record_ct": 10}
    ProfileResult.scale_sampled_estimates(row, 1.15)
    assert row["record_ct"] == 12


def test_absent_columns_are_not_added():
    row = {"record_ct": 300, "distinct_value_ct": 5}
    ProfileResult.scale_sampled_estimates(row, 2.0)
    assert set(row) == {"record_ct", "distinct_value_ct", "sample_ratio"}


def test_null_and_nan_counts_are_left_for_write_time_sanitizing():
    row = {"record_ct": None, "value_ct": float("nan"), "null_value_ct": 4}
    ProfileResult.scale_sampled_estimates(row, 2.0)
    assert row["record_ct"] is None
    assert row["value_ct"] != row["value_ct"]
    assert row["null_value_ct"] == 8


def test_counts_returned_as_decimal_or_float_are_scaled_to_integers():
    row = {"record_ct": Decimal(300), "value_ct": 299.0}
    ProfileResult.scale_sampled_estimates(row, 10000 / 3000)
    assert row["record_ct"] == 1000
    assert row["value_ct"] == 997
