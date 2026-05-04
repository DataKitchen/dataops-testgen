from unittest.mock import MagicMock, patch

import pytest

from testgen.commands.queries.profiling_query import ProfilingSQL, calculate_sampling_params

pytestmark = pytest.mark.unit


# --- ProfilingSQL.update_profiling_results ---


def _make_profiling_sql(profile_flag_pii=False, profile_flag_cdes=False):
    connection = MagicMock()
    table_group = MagicMock()
    table_group.profile_flag_pii = profile_flag_pii
    table_group.profile_flag_cdes = profile_flag_cdes
    profiling_run = MagicMock()
    return ProfilingSQL(connection, table_group, profiling_run)


@pytest.mark.parametrize("profile_flag_pii,profile_flag_cdes", [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
])
def test_update_profiling_results_weight_query_is_always_last(profile_flag_pii, profile_flag_cdes):
    sql = _make_profiling_sql(profile_flag_pii=profile_flag_pii, profile_flag_cdes=profile_flag_cdes)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert templates[-1] == "dq_score_weight_update.sql"


def test_update_profiling_results_includes_pii_queries_when_flag_set():
    sql = _make_profiling_sql(profile_flag_pii=True)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert "pii_flag.sql" in templates
    assert "pii_flag_update.sql" in templates


def test_update_profiling_results_excludes_pii_queries_when_flag_unset():
    sql = _make_profiling_sql(profile_flag_pii=False)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert "pii_flag.sql" not in templates
    assert "pii_flag_update.sql" not in templates


def test_update_profiling_results_includes_cde_query_when_flag_set():
    sql = _make_profiling_sql(profile_flag_cdes=True)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert "cde_flagger_query.sql" in templates


def test_update_profiling_results_excludes_cde_query_when_flag_unset():
    sql = _make_profiling_sql(profile_flag_cdes=False)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert "cde_flagger_query.sql" not in templates


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
