from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.profile_result import ColumnErrorRow, MeasureAcquisition, ProfileResult


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


# --- ProfileResult.calibrate_sampled_counts ---

SAMPLEABLE_COUNTS = {
    "zero_length_ct",
    "lead_space_ct",
    "quoted_value_ct",
    "includes_digit_ct",
    "filled_value_ct",
    "upper_case_ct",
    "lower_case_ct",
    "non_alpha_ct",
    "non_printing_ct",
    "numeric_ct",
    "date_ct",
    "embedded_space_ct",
    "frequent_patterns",
    "frequent_values",
}


def test_calibrates_exactly_the_sampleable_counts():
    calibrated = {
        column
        for column, acquisition in ProfileResult.measure_acquisition.items()
        if acquisition is MeasureAcquisition.SAMPLEABLE_COUNT
    }
    assert calibrated == SAMPLEABLE_COUNTS


def test_a_count_covering_every_sampled_value_lands_on_value_ct():
    row = {
        "value_ct": 1000,
        "sample_value_ct": 300,
        "sample_pattern_value_ct": 300,
        "numeric_ct": 300,
        "lead_space_ct": 7,
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert row == {"value_ct": 1000, "numeric_ct": 1000, "lead_space_ct": 23}


def test_letter_case_counts_leave_no_mixed_case_values_the_sample_did_not_have():
    row = {
        "value_ct": 1000,
        "sample_value_ct": 300,
        "sample_pattern_value_ct": 300,
        "upper_case_ct": 298,
        "lower_case_ct": 1,
        "non_alpha_ct": 1,
    }
    ProfileResult.calibrate_sampled_counts(row)
    # Rounded one by one, these would be 993 + 3 + 3, leaving one mixed-case value.
    assert row["upper_case_ct"] + row["lower_case_ct"] + row["non_alpha_ct"] == 1000


def test_letter_case_counts_and_the_mixed_case_values_they_leave_add_up_to_value_ct():
    row = {
        "value_ct": 1000,
        "sample_value_ct": 300,
        "sample_pattern_value_ct": 300,
        "upper_case_ct": 101,
        "lower_case_ct": 101,
        "non_alpha_ct": 1,
    }
    ProfileResult.calibrate_sampled_counts(row)
    # Exact shares 336.67 + 336.67 + 3.33 leave 323.33 mixed-case values.
    assert (row["upper_case_ct"], row["lower_case_ct"], row["non_alpha_ct"]) == (337, 337, 3)


def test_letter_case_ties_go_to_the_earlier_count():
    row = {
        "value_ct": 5,
        "sample_value_ct": 2,
        "sample_pattern_value_ct": 2,
        "upper_case_ct": 1,
        "lower_case_ct": 1,
        "non_alpha_ct": 0,
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert (row["upper_case_ct"], row["lower_case_ct"], row["non_alpha_ct"]) == (3, 2, 0)


def test_letter_case_counts_with_a_null_are_lifted_one_by_one():
    row = {
        "value_ct": 1000,
        "sample_value_ct": 300,
        "sample_pattern_value_ct": 300,
        "upper_case_ct": 298,
        "lower_case_ct": None,
        "non_alpha_ct": 1,
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert (row["upper_case_ct"], row["lower_case_ct"], row["non_alpha_ct"]) == (993, None, 3)


def test_whole_table_and_as_measured_values_are_left_alone():
    row = {
        "record_ct": 1200,
        "value_ct": 1000,
        "null_value_ct": 200,
        "distinct_value_ct": 280,
        "distinct_std_value_ct": 270,
        "zero_value_ct": 4,
        "min_text": "a",
        "sample_value_ct": 300,
        "sample_pattern_value_ct": 300,
        "distinct_pattern_ct": 12,
        "avg_embedded_spaces": 1.5,
        "std_pattern_match": "EMAIL",
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert row == {
        "record_ct": 1200,
        "value_ct": 1000,
        "null_value_ct": 200,
        "distinct_value_ct": 280,
        "distinct_std_value_ct": 270,
        "zero_value_ct": 4,
        "min_text": "a",
        "distinct_pattern_ct": 12,
        "avg_embedded_spaces": 1.5,
        "std_pattern_match": "EMAIL",
    }


def test_frequent_pattern_counts_are_calibrated():
    row = {
        "value_ct": 1000,
        "sample_value_ct": 250,
        "sample_pattern_value_ct": 300,
        "frequent_patterns": {"values": [{"value": "NNN", "ct": 240}, {"value": "AAA", "ct": 60}]},
    }
    ProfileResult.calibrate_sampled_counts(row)
    # Lifted by the pattern read's own value count, not by the 250 the other sample read held.
    assert row["frequent_patterns"] == {"values": [{"value": "NNN", "ct": 800}, {"value": "AAA", "ct": 200}]}


def test_an_unsampled_row_keeps_its_counts():
    row = {
        "value_ct": 300,
        "sample_value_ct": 300,
        "sample_pattern_value_ct": 300,
        "numeric_ct": 299,
        "lead_space_ct": 7,
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert row == {"value_ct": 300, "numeric_ct": 299, "lead_space_ct": 7}


def test_a_sample_without_values_leaves_the_counts_unknown():
    row = {
        "value_ct": 50,
        "sample_value_ct": 0,
        "sample_pattern_value_ct": 0,
        "numeric_ct": 0,
        "zero_length_ct": 0,
        "frequent_patterns": None,
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert row == {"value_ct": 50, "numeric_ct": None, "zero_length_ct": None, "frequent_patterns": None}


def test_patterns_are_lifted_when_only_the_other_sample_read_held_no_values():
    row = {
        "value_ct": 50,
        "sample_value_ct": 0,
        "sample_pattern_value_ct": 5,
        "numeric_ct": 0,
        "frequent_patterns": {"values": [{"value": "NNNNN", "ct": 2}]},
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert row == {"value_ct": 50, "numeric_ct": None, "frequent_patterns": {"values": [{"value": "NNNNN", "ct": 20}]}}


def test_ties_round_away_from_zero():
    row = {"value_ct": 5, "sample_value_ct": 2, "sample_pattern_value_ct": 2, "numeric_ct": 1}
    ProfileResult.calibrate_sampled_counts(row)
    assert row["numeric_ct"] == 3  # 2.5 -> 3, not banker's 2


def test_null_and_nan_counts_stay_null():
    row = {
        "value_ct": 1000,
        "sample_value_ct": 300,
        "sample_pattern_value_ct": 300,
        "numeric_ct": None,
        "date_ct": float("nan"),
        "lead_space_ct": 3,
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert row == {"value_ct": 1000, "numeric_ct": None, "date_ct": None, "lead_space_ct": 10}


def test_counts_returned_as_decimal_or_float_are_calibrated_to_integers():
    row = {
        "value_ct": Decimal(1000),
        "sample_value_ct": Decimal(300),
        "sample_pattern_value_ct": Decimal(300),
        "numeric_ct": Decimal(299),
        "date_ct": 150.0,
    }
    ProfileResult.calibrate_sampled_counts(row)
    assert row["numeric_ct"] == 997
    assert row["date_ct"] == 500
    assert isinstance(row["numeric_ct"], int)
    assert isinstance(row["date_ct"], int)


def test_a_row_without_a_sample_value_count_is_left_as_it_is():
    row = {"value_ct": 1000, "numeric_ct": 300}
    ProfileResult.calibrate_sampled_counts(row)
    assert row == {"value_ct": 1000, "numeric_ct": 300}


@patch("testgen.common.models.profile_result.ProfileResult._paginate", return_value=([], 0))
def test_list_column_errors_for_run_reads_one_run_with_errors(mock_paginate):
    run_id = uuid4()

    ProfileResult.list_column_errors_for_run(run_id, ProfileResult.table_name == "orders", limit=20)

    query = mock_paginate.call_args.args[0]
    where = str(query.whereclause)
    assert "profile_results.profile_run_id = :profile_run_id_1" in where
    assert "profile_results.query_error IS NOT NULL" in where
    assert "profile_results.table_name = :table_name_1" in where
    assert query._order_by_clauses
    assert mock_paginate.call_args.kwargs == {"page": 1, "limit": 20, "data_class": ColumnErrorRow}


def test_the_column_pass_calibration_leaves_frequent_values_alone():
    frequent = {"values": [{"value": "A", "ct": 3}]}
    row = {"value_ct": 1000, "sample_value_ct": 300, "sample_pattern_value_ct": 300, "frequent_values": frequent}
    ProfileResult.calibrate_sampled_counts(row)
    assert row["frequent_values"] == {"values": [{"value": "A", "ct": 3}]}


# --- ProfileResult.calibrate_frequent_values ---


def test_frequent_value_counts_are_lifted_and_the_other_distinct_count_is_kept():
    frequent = {"values": [{"value": "A", "ct": 240}, {"value": "B", "ct": 30}], "other": {"distinct_ct": 12, "ct": 15}}
    ProfileResult.calibrate_frequent_values(frequent, 1000, 300)
    assert frequent == {"values": [{"value": "A", "ct": 800}, {"value": "B", "ct": 100}], "other": {"distinct_ct": 12, "ct": 50}}


def test_frequent_values_covering_every_sampled_value_land_on_the_value_count():
    frequent = {"values": [{"value": "A", "ct": Decimal(299)}]}
    ProfileResult.calibrate_frequent_values(frequent, Decimal(1001), 299.0)
    assert frequent == {"values": [{"value": "A", "ct": 1001}]}


@pytest.mark.parametrize(("whole", "sampled"), [(None, 300), (1000, None), (1000, 0), (1000, float("nan"))])
def test_frequent_values_without_a_ratio_are_left_as_counted(whole, sampled):
    frequent = {"values": [{"value": "A", "ct": 3}], "other": {"distinct_ct": 2, "ct": 1}}
    ProfileResult.calibrate_frequent_values(frequent, whole, sampled)
    assert frequent == {"values": [{"value": "A", "ct": 3}], "other": {"distinct_ct": 2, "ct": 1}}


def test_missing_frequent_values_are_accepted():
    ProfileResult.calibrate_frequent_values(None, 1000, 300)
