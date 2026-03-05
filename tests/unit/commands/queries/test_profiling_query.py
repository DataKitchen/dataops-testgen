import pytest

from testgen.commands.queries.profiling_query import calculate_sampling_params

pytestmark = pytest.mark.unit


# --- calculate_sampling_params ---


def test_sampling_basic_calculation():
    result = calculate_sampling_params("orders", 10000, "30", min_sample=100)
    assert result is not None
    assert result.table_name == "orders"
    assert result.sample_count == 3000
    assert result.sample_ratio == pytest.approx(10000 / 3000)
    assert result.sample_percent == pytest.approx(30.0)


def test_sampling_non_numeric_percent_fallback():
    """Non-numeric string should fall back to 30%."""
    result = calculate_sampling_params("orders", 10000, "abc", min_sample=100)
    assert result is not None
    assert result.sample_count == 3000


def test_sampling_empty_string_percent_fallback():
    result = calculate_sampling_params("orders", 10000, "", min_sample=100)
    assert result is not None
    assert result.sample_count == 3000


def test_sampling_none_percent_fallback():
    result = calculate_sampling_params("orders", 10000, None, min_sample=100)
    assert result is not None
    assert result.sample_count == 3000


def test_sampling_percent_out_of_range_zero():
    result = calculate_sampling_params("orders", 10000, "0", min_sample=100)
    assert result is None


def test_sampling_percent_out_of_range_100():
    result = calculate_sampling_params("orders", 10000, "100", min_sample=100)
    assert result is None


def test_sampling_record_count_below_min_sample():
    result = calculate_sampling_params("small_table", 50, "30", min_sample=100)
    assert result is None


def test_sampling_record_count_equals_min_sample():
    result = calculate_sampling_params("small_table", 100, "30", min_sample=100)
    assert result is None


def test_sampling_clamped_to_min_sample():
    """When calculated sample is below min_sample, clamp up to min_sample."""
    result = calculate_sampling_params("orders", 1000, "5", min_sample=200)
    # 5% of 1000 = 50, but min_sample is 200
    assert result is not None
    assert result.sample_count == 200


def test_sampling_clamped_to_max_sample():
    """When calculated sample exceeds max, clamp down to max."""
    result = calculate_sampling_params("huge_table", 10_000_000, "50", min_sample=100, max_sample=999000)
    # 50% of 10M = 5M, but max is 999000
    assert result is not None
    assert result.sample_count == 999000


def test_sampling_ratio_and_percent_math():
    result = calculate_sampling_params("orders", 5000, "20", min_sample=100)
    # 20% of 5000 = 1000
    assert result.sample_count == 1000
    assert result.sample_ratio == pytest.approx(5.0)
    assert result.sample_percent == pytest.approx(20.0)


def test_sampling_float_percent():
    result = calculate_sampling_params("orders", 10000, 25.5, min_sample=100)
    # 25.5% of 10000 = 2550
    assert result is not None
    assert result.sample_count == 2550


def test_sampling_decimal_string_percent():
    result = calculate_sampling_params("orders", 10000, "15.5", min_sample=100)
    assert result is not None
    assert result.sample_count == 1550
