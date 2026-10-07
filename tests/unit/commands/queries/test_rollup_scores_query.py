import re

import pytest

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL

pytestmark = pytest.mark.unit


def test_prevalence_scores_a_failure_without_a_measure_when_the_formula_does_not_use_it():
    query, _ = RollupScoresSQL("run-id").rollup_test_scores(update_prevalence=True)[0]
    measure_filters = re.findall(r"AND (.*result_measure IS NOT NULL.*)", query)

    assert measure_filters == [
        "(r.result_measure IS NOT NULL OR tt.dq_score_prevalence_formula NOT LIKE '%{RESULT_MEASURE}%')",
    ] * 2
