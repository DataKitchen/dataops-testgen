"""A Log result is recorded without passing or failing, so it stays out of the Testing Score the way a
muted result does."""

import re
from importlib.resources import files

import pytest

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL

pytestmark = pytest.mark.unit

RUN_ID = "11111111-1111-1111-1111-111111111111"
TABLE_GROUP_ID = "22222222-2222-2222-2222-222222222222"
CONFIRMED = "COALESCE(r.disposition, 'Confirmed') = 'Confirmed'"
NOT_LOG = "r.result_status IS DISTINCT FROM 'Log'"


def _statements(template: str) -> list[str]:
    queries = RollupScoresSQL(RUN_ID, TABLE_GROUP_ID)
    query, _ = queries._get_query(template)
    return query.split(";")


def test_a_log_result_gets_no_record_count_or_prevalence():
    # The first statement initializes every result before the failing ones get their prevalence
    initialize = next(s for s in _statements("calc_prevalence_test_results.sql") if "UPDATE test_results" in s)

    assert re.search(r"dq_record_ct = CASE WHEN r\.result_status = 'Log' THEN NULL ELSE tc\.record_ct END", initialize)
    assert re.search(r"dq_prevalence = CASE WHEN r\.result_status = 'Log' THEN NULL ELSE 0 END", initialize)


def test_a_failing_log_result_gets_no_prevalence():
    calculations = [s for s in _statements("calc_prevalence_test_results.sql") if "dq_prevalence = LEAST" in s]

    assert len(calculations) == 2
    for calculation in calculations:
        assert "AND r.result_status <> 'Log'" in calculation


@pytest.mark.parametrize(
    ("template", "rollups"),
    [("rollup_scores_test_run.sql", 1), ("rollup_scores_test_table_group.sql", 2)],
)
def test_every_rollup_that_drops_a_muted_result_drops_a_log_result(template, rollups):
    # Each rollup filters its results in one WHERE clause, which ends at its GROUP BY
    where_clauses = [
        query[query.index(CONFIRMED):].split("GROUP BY")[0]
        for query in _statements(template)
        if CONFIRMED in query
    ]

    assert len(where_clauses) == rollups
    for where_clause in where_clauses:
        assert NOT_LOG in where_clause


def test_every_test_scoring_view_drops_a_log_result():
    # The views read stored prevalence, which a Log result keeps until its run is scored again
    views_sql = (files("testgen.template") / "dbsetup" / "060_create_standard_views.sql").read_text()
    test_scoring_views = [
        view for view in views_sql.split("CREATE VIEW ")[1:] if view.startswith("v_dq_test_scoring_")
    ]

    assert len(test_scoring_views) == 4
    for view in test_scoring_views:
        assert "WHERE r.dq_prevalence IS NOT NULL" in view
        assert NOT_LOG in view
