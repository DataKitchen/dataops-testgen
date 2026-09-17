from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.queries.rollup_scores_query import RollupScoresSQL
from testgen.common.database.database_service import replace_params
from testgen.common.models.scores import ScoreDefinitionResultHistoryEntry
from testgen.common.models.suite_version import SuiteVersion
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


def test_the_table_group_rollup_counts_only_runs_of_the_active_version():
    queries = RollupScoresSQL("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    query, _ = queries.rollup_test_scores(update_table_group=True)[-1]
    cte = _latest_run_per_suite_cte(query)

    assert "AND (run.version_id IS NULL OR run.version_id =" in cte
    # Proves the rendering came from active_for_sql, not resolved_for_sql: the latter's draft
    # branch would inject "frozen_at IS NULL" into this same CTE.
    assert "frozen_at IS NULL" not in cte


def test_score_history_pins_only_runs_of_the_active_version():
    sql = replace_params(
        read_template_sql_file("add_latest_runs.sql", "score_cards"),
        {"ACTIVE_VERSION": SuiteVersion.active_for_sql("r.test_suite_id")},
    )
    cte = _ranked_test_runs_cte(sql)

    assert "AND (r.version_id IS NULL OR r.version_id =" in cte


def test_score_history_keeps_runs_that_predate_the_placeholders_freeze_time():
    # The placeholder's freeze time is the install-or-upgrade timestamp, so a preview guard
    # written without the suite-owned qualifier drops every historical regular-suite run.
    sql = read_template_sql_file("add_latest_runs.sql", "score_cards")
    cte = _ranked_test_runs_cte(sql)

    assert "AND (sv.test_suite_id IS NULL OR r.test_starttime >= sv.frozen_at" in cte


def test_the_table_group_rollup_counts_runs_written_before_versioning_existed():
    # test_runs.version_id is nullable with no backfill: every run written before this work
    # has version_id NULL, and NULL = anything is NULL, not true, so the active-version equality
    # alone would silently drop every pre-upgrade run out of its table group's score.
    queries = RollupScoresSQL("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    query, _ = queries.rollup_test_scores(update_table_group=True)[-1]
    cte = _latest_run_per_suite_cte(query)

    assert "run.version_id IS NULL OR run.version_id =" in cte


def test_score_history_pins_runs_written_before_versioning_existed():
    sql = replace_params(
        read_template_sql_file("add_latest_runs.sql", "score_cards"),
        {"ACTIVE_VERSION": SuiteVersion.active_for_sql("r.test_suite_id")},
    )
    cte = _ranked_test_runs_cte(sql)

    assert "r.version_id IS NULL OR r.version_id =" in cte


def test_score_history_preview_guard_admits_runs_written_before_versioning_existed():
    # sv.id = r.version_id in the EXISTS carve-out matches nothing when r.version_id is NULL, so
    # the preview guard itself needs the same NULL tolerance, not only the equality above it.
    sql = read_template_sql_file("add_latest_runs.sql", "score_cards")
    cte = _ranked_test_runs_cte(sql)

    assert "AND (r.version_id IS NULL OR EXISTS" in cte


def test_the_table_group_rollup_excludes_a_preview_run_of_a_freshly_frozen_version():
    # freeze_version freezes the same suite_versions.id a draft already had, so every preview run
    # made while that version was a draft carries the exact id that becomes ACTIVE_VERSION at the
    # instant of freezing. Without this guard, DISTINCT ON ... ORDER BY test_starttime DESC would
    # surface that preview run as the suite's scored run the moment the version freezes.
    queries = RollupScoresSQL("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    query, _ = queries.rollup_test_scores(update_table_group=True)[-1]
    cte = _latest_run_per_suite_cte(query)

    assert "AND (sv.test_suite_id IS NULL OR run.test_starttime >= sv.frozen_at" in cte


def test_the_table_group_rollup_preview_guard_admits_runs_written_before_versioning_existed():
    # sv.id = run.version_id in the EXISTS carve-out matches nothing when run.version_id is NULL,
    # so the preview guard itself needs the same NULL tolerance as the equality above it.
    queries = RollupScoresSQL("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
    query, _ = queries.rollup_test_scores(update_table_group=True)[-1]
    cte = _latest_run_per_suite_cte(query)

    assert "AND (run.version_id IS NULL OR EXISTS" in cte


def test_add_as_cutoff_hands_postgres_the_resolved_query_not_the_raw_placeholder():
    # The three tests above build their SQL by calling active_for_sql directly, so none of them
    # goes through add_as_cutoff itself. A dropped replace_params call there would leave
    # "{ACTIVE_VERSION}" in the text handed to Postgres and break score-history refresh at
    # runtime while every one of those tests stayed green.
    entry = ScoreDefinitionResultHistoryEntry(
        definition_id=uuid4(),
        category="dq_dimension",
        last_run_time=datetime(2024, 1, 1),
    )
    entry.definition = MagicMock(project_code="demo")

    session = MagicMock()
    with patch("testgen.common.models.scores.get_current_session", return_value=session):
        entry.add_as_cutoff()

    executed_sql = str(session.execute.call_args.args[0])

    assert "{ACTIVE_VERSION}" not in executed_sql
    assert "r.version_id =" in executed_sql
    # Proves the rendering came from active_for_sql, not resolved_for_sql: the latter's draft
    # branch would inject "frozen_at IS NULL" into this same query.
    assert "frozen_at IS NULL" not in executed_sql
