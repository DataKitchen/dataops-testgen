import duckdb
import pytest

from testgen.common.models.profile_result import ProfileResult

pytestmark = pytest.mark.unit


@pytest.fixture
def profile_rows():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE profile_results (name VARCHAR, sample_ratio DOUBLE, value_ct INT)"
    )
    con.executemany(
        "INSERT INTO profile_results VALUES (?, ?, ?)",
        [
            ("unsampled", None, 5),
            ("sampled", 2.5, 5),
            ("sampled_without_values", 2.5, 0),
            ("sampled_value_ct_unknown", 2.5, None),
        ],
    )

    def matching(criteria: str) -> set[str]:
        return {name for (name,) in con.execute(f"SELECT name FROM profile_results WHERE {criteria}").fetchall()}

    return matching


def test_a_sampled_measure_is_exact_where_nothing_was_sampled(profile_rows):
    assert profile_rows(ProfileResult.exact_clause(["lead_space_ct", "frequent_values"])) == {
        "unsampled",
        "sampled_without_values",
    }


@pytest.mark.parametrize("measure", ["record_ct", "distinct_value_ct", "percentile_50"])
def test_a_measure_never_taken_from_the_sample_is_rejected(measure):
    with pytest.raises(ValueError, match=f"'{measure}' is measured over every row even when profiling samples"):
        ProfileResult.exact_clause([measure])


def test_an_unknown_measure_is_rejected():
    with pytest.raises(ValueError, match="'zero_lenght_ct' is not a profiling measure"):
        ProfileResult.exact_clause(["zero_lenght_ct"])


def test_declared_measures_restrict_the_whole_criteria(profile_rows):
    criteria = ProfileResult.apply_exact_measures("name = 'sampled' OR value_ct = 5", ["zero_length_ct"])

    assert profile_rows(criteria) == {"unsampled"}


def test_a_token_restricts_only_the_expression_it_sits_in(profile_rows):
    criteria = ProfileResult.apply_exact_measures(
        "value_ct > 0 AND NOT COALESCE(value_ct = 5 AND {EXACT:filled_value_ct,zero_length_ct}, FALSE)", None
    )

    assert profile_rows(criteria) == {"sampled"}


def test_a_token_naming_an_unknown_measure_is_rejected():
    with pytest.raises(ValueError, match="not a profiling measure"):
        ProfileResult.apply_exact_measures("{EXACT:no_such_measure}", None)
