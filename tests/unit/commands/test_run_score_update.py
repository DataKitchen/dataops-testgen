from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from testgen.commands import run_score_update as module
from testgen.common.enums import JobKey

pytestmark = pytest.mark.unit


def _templates(execute_rollup_queries: MagicMock) -> list[str]:
    return [query for queries in execute_rollup_queries.call_args_list for query, _ in queries.args[0]]


@pytest.fixture
def session(db_session_mock):
    with patch.object(module, "get_current_session", return_value=db_session_mock):
        yield db_session_mock


def test_a_test_run_rolls_up_its_own_scores_and_requests_a_refresh_of_its_table_group(session):
    run_id, table_group_id, started = uuid4(), uuid4(), datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    session.execute.return_value.first.return_value = MagicMock(
        test_starttime=started, table_groups_id=table_group_id, project_code="DEFAULT",
    )
    with (
        patch.object(module, "execute_rollup_queries") as execute_rollup_queries,
        patch.object(module.JobExecution, "request_project_score_refresh") as request,
    ):
        module.rollup_run_and_request_refresh(str(run_id), JobKey.run_tests)

    templates = " ".join(_templates(execute_rollup_queries))
    assert "UPDATE test_runs" in templates
    assert "pg_advisory_xact_lock" not in templates
    request.assert_called_once_with(
        "DEFAULT", profile_table_group_ids=[], test_table_group_ids=[str(table_group_id)], refresh_date=started,
    )


def test_a_profiling_run_requests_a_refresh_of_its_table_group_profiling_scores(session):
    profiling_run = MagicMock(project_code="DEFAULT", table_groups_id=uuid4(), profiling_starttime=None)
    session.scalars.return_value.first.return_value = profiling_run
    with (
        patch.object(module, "execute_rollup_queries") as execute_rollup_queries,
        patch.object(module.JobExecution, "request_project_score_refresh") as request,
    ):
        module.rollup_run_and_request_refresh(str(uuid4()), JobKey.run_profile)

    assert "pg_advisory_xact_lock" not in " ".join(_templates(execute_rollup_queries))
    request.assert_called_once_with(
        "DEFAULT",
        profile_table_group_ids=[str(profiling_run.table_groups_id)],
        test_table_group_ids=[],
        refresh_date=None,
    )


def test_a_missing_run_requests_no_refresh(session):
    session.execute.return_value.first.return_value = None
    with (
        patch.object(module, "execute_rollup_queries") as execute_rollup_queries,
        patch.object(module.JobExecution, "request_project_score_refresh") as request,
    ):
        module.rollup_run_and_request_refresh(str(uuid4()), JobKey.run_tests)

    execute_rollup_queries.assert_not_called()
    request.assert_not_called()


def test_a_project_refresh_rolls_up_each_table_group_then_refreshes_their_scorecards(session):
    with (
        patch.object(module, "RollupScoresSQL") as rollup_sql,
        patch.object(module, "execute_rollup_queries"),
        patch.object(module, "run_refresh_score_cards_results") as refresh,
    ):
        module.run_project_score_refresh(
            "DEFAULT",
            profile_table_group_ids=["tg-1"],
            test_table_group_ids=["tg-1", "tg-2"],
            refresh_date="2026-10-01T12:00:00+00:00",
        )

    assert rollup_sql.call_args_list == [call(None, "tg-1"), call(None, "tg-1"), call(None, "tg-2")]
    assert rollup_sql.return_value.rollup_profiling_table_group.call_count == 1
    assert rollup_sql.return_value.rollup_test_table_group.call_count == 2
    refresh.assert_called_once_with(
        project_code="DEFAULT",
        add_history_entry=True,
        refresh_date=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        table_group_ids={"tg-1", "tg-2"},
    )


def test_inline_score_update_rolls_up_the_run_and_refreshes_its_table_group(session):
    table_group_id, started = uuid4(), datetime(2026, 10, 1, 12, 0)
    session.execute.return_value.first.return_value = MagicMock(
        test_starttime=started, table_groups_id=table_group_id, project_code="DEFAULT",
    )
    with (
        patch.object(module, "execute_rollup_queries"),
        patch.object(module.JobExecution, "request_project_score_refresh") as request,
        patch.object(module, "run_refresh_score_cards_results") as refresh,
    ):
        module.run_score_update(str(uuid4()), JobKey.run_tests)

    request.assert_not_called()
    refresh.assert_called_once_with(
        project_code="DEFAULT",
        add_history_entry=True,
        refresh_date=started,
        table_group_ids={str(table_group_id)},
    )
