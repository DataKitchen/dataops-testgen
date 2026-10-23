import math

import pytest

from testgen.common.models.profile_result import (
    MeasureAcquisition,
    MeasureProvenance,
    PercentileMethod,
    ProfileResult,
    sample_percent_label,
)

pytestmark = pytest.mark.unit

SAMPLED_ROW = {
    "general_type": "A", "sample_ratio": 10 / 3, "percentile_method": PercentileMethod.APPROXIMATE, "value_ct": 500,
}
EXACT_ROW = {"general_type": "A", "sample_ratio": None, "percentile_method": PercentileMethod.EXACT, "value_ct": 500}


def _measures(*acquisitions: MeasureAcquisition) -> list[str]:
    return [name for name, measure in ProfileResult.measures.items() if measure.acquisition in acquisitions]


@pytest.mark.parametrize("measure", _measures(MeasureAcquisition.WHOLE_TABLE))
def test_whole_table_measures_are_exact_on_a_sampled_row(measure):
    assert ProfileResult.provenance(measure, SAMPLED_ROW) == MeasureProvenance.EXACT


@pytest.mark.parametrize("measure", _measures(MeasureAcquisition.SAMPLEABLE, MeasureAcquisition.SAMPLEABLE_COUNT))
def test_sample_measures_follow_the_row_sample_ratio(measure):
    assert ProfileResult.provenance(measure, SAMPLED_ROW) == MeasureProvenance.SAMPLED
    assert ProfileResult.provenance(measure, EXACT_ROW) == MeasureProvenance.EXACT


@pytest.mark.parametrize("measure", ["frequent_patterns", "percentile_50"])
def test_a_column_with_no_values_is_exact(measure):
    """Matches ``exact_clause``: a column with no values gives the sample nothing to count."""
    assert ProfileResult.provenance(measure, {**SAMPLED_ROW, "value_ct": 0}) == MeasureProvenance.EXACT


@pytest.mark.parametrize(
    "percentile_method,expected",
    [
        (PercentileMethod.APPROXIMATE, MeasureProvenance.APPROXIMATE),
        (PercentileMethod.EXACT, MeasureProvenance.EXACT),
        # Row with no recorded percentile method
        (None, MeasureProvenance.EXACT),
    ],
)
def test_percentiles_follow_the_percentile_method(percentile_method, expected):
    row = {**SAMPLED_ROW, "percentile_method": percentile_method}

    assert ProfileResult.provenance("percentile_50", row) == expected


def test_pandas_nulls_read_as_not_sampled():
    row = {"sample_ratio": math.nan, "percentile_method": math.nan, "value_ct": 500}

    assert ProfileResult.provenance_details(row) == {"kinds": {}, "descriptions": {}}


def test_details_cover_only_the_measures_that_are_not_exact():
    details = ProfileResult.provenance_details(SAMPLED_ROW)

    sampled = _measures(MeasureAcquisition.SAMPLEABLE, MeasureAcquisition.SAMPLEABLE_COUNT)
    percentiles = _measures(MeasureAcquisition.PERCENTILE)
    assert details["kinds"] == {
        **dict.fromkeys(sampled, MeasureProvenance.SAMPLED),
        **dict.fromkeys(percentiles, MeasureProvenance.APPROXIMATE),
    }
    assert details["descriptions"] == {
        MeasureProvenance.SAMPLED: "Estimated from a 30% sample",
        MeasureProvenance.APPROXIMATE: "Approximate: computed over every row with an approximate percentile function",
    }


@pytest.mark.parametrize(
    "sample_ratio,expected",
    [(10 / 3, "30%"), (4, "25%"), (250, "0.4%"), (2002, "0.05%"), (1.0001, "99.9%"), (1.005, "99.5%")],
)
def test_sample_percent_label(sample_ratio, expected):
    assert sample_percent_label(sample_ratio) == expected
