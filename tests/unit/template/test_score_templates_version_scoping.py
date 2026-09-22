import re

import pytest

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.common.read_file import read_template_sql_file

pytestmark = pytest.mark.unit


def _section(text: str, start: str, end: str) -> str:
    """The text between (and including) two markers, so an assertion can be pinned to one CTE.

    A substring check against the whole rendered query is satisfied by a clause anywhere in the
    file, including one attached to the wrong CTE. Isolating the CTE's own text first makes that
    kind of mutation visible.
    """
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def _latest_run_per_suite_cte(query: str) -> str:
    return _section(query, "WITH latest_run_per_suite", "score_calc\n  AS (SELECT ts.table_groups_id,")


def _ranked_test_runs_cte(sql: str) -> str:
    return _section(
        sql,
        "WITH ranked_test_runs",
        "INSERT INTO score_history_latest_runs\n       (definition_id, score_history_cutoff_time, test_suite_id, last_test_run_id)",
    )


def _table_group_rollup() -> str:
    queries = RollupScoresSQL("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    query, _ = queries.rollup_test_scores(update_table_group=True)[-1]
    return _latest_run_per_suite_cte(query)


def _score_history_cte() -> str:
    return _ranked_test_runs_cte(read_template_sql_file("add_latest_runs.sql", "score_cards"))


@pytest.mark.parametrize("cte", [_table_group_rollup, _score_history_cte])
def test_a_freeze_does_not_take_the_suite_out_of_the_score(cte):
    # freeze_version freezes a version no run carries yet, so pinning the scored run to the
    # version in force would drop the suite out of every score between the freeze and the
    # first run of the new version, with no data change behind the move.
    assert not re.search(r"version_id\s*=\s*\(?\s*coalesce", cte(), re.IGNORECASE)


@pytest.mark.parametrize("cte", [_table_group_rollup, _score_history_cte])
def test_only_a_run_of_a_version_that_was_in_force_when_it_ran_is_scored(cte):
    # A draft has no freeze time, so >= is NULL rather than true: the same predicate that
    # admits a superseded version's run excludes every draft preview, including one made
    # while the version it previewed was still a draft.
    assert "run.test_starttime >= sv.frozen_at" in cte() or "r.test_starttime >= sv.frozen_at" in cte()


@pytest.mark.parametrize("cte", [_table_group_rollup, _score_history_cte])
def test_the_placeholder_is_exempt_from_the_freeze_time_check(cte):
    # The placeholder's freeze time is the install-or-upgrade timestamp, so a guard written
    # without the suite-owned carve-out drops every historical regular-suite run.
    assert "sv.test_suite_id IS NULL OR" in cte()


@pytest.mark.parametrize("cte", [_table_group_rollup, _score_history_cte])
def test_runs_written_before_versioning_existed_are_scored(cte):
    # test_runs.version_id is nullable with no backfill, and sv.id = <NULL> in the carve-out
    # matches nothing, so the guard needs its own NULL tolerance.
    assert re.search(r"\(\s*r(un)?\.version_id IS NULL OR EXISTS", cte())


@pytest.mark.parametrize("sql", [
    lambda: RollupScoresSQL("1", "2").rollup_test_scores(update_table_group=True)[-1][0],
    lambda: read_template_sql_file("add_latest_runs.sql", "score_cards"),
])
def test_no_unresolved_placeholder_reaches_postgres(sql):
    # These templates carry {...} placeholders resolved by replace_params before execution; one
    # left behind is a syntax error at runtime that no assertion on a rendered CTE would catch.
    assert not re.search(r"\{[A-Z_]+\}", sql())
