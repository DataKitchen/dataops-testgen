from unittest.mock import MagicMock, Mock, call, patch
from uuid import uuid4

import pytest

from testgen.commands.run_recalculate_project_scores import run_recalculate_project_scores

pytestmark = pytest.mark.unit

MODULE = "testgen.commands.run_recalculate_project_scores"


def _make_db_ctx(scalars_result):
    session = MagicMock()
    session.scalars.return_value.all.return_value = scalars_result
    ctx = MagicMock()
    ctx.__enter__ = Mock(return_value=session)
    ctx.__exit__ = Mock(return_value=False)
    return ctx


def _make_table_group(last_complete_profile_run_id=None):
    tg = MagicMock()
    tg.id = uuid4()
    tg.last_complete_profile_run_id = last_complete_profile_run_id
    return tg


def _make_test_suite(last_complete_test_run_id=None):
    ts = MagicMock()
    ts.id = uuid4()
    ts.last_complete_test_run_id = last_complete_test_run_id or uuid4()
    return ts


def test_no_table_groups_only_calls_refresh():
    with (
        patch(f"{MODULE}.database_session", side_effect=[_make_db_ctx([])]),
        patch(f"{MODULE}.execute_db_queries") as mock_exec,
        patch(f"{MODULE}.RollupScoresSQL") as mock_rollup_cls,
        patch(f"{MODULE}.run_refresh_score_cards_results") as mock_refresh,
    ):
        run_recalculate_project_scores("proj")

    mock_exec.assert_not_called()
    mock_rollup_cls.assert_not_called()
    mock_refresh.assert_called_once_with(project_code="proj")


def test_table_group_without_profile_run_skips_profiling_rollup():
    tg = _make_table_group(last_complete_profile_run_id=None)

    with (
        patch(f"{MODULE}.database_session", side_effect=[_make_db_ctx([tg]), _make_db_ctx([])]),
        patch(f"{MODULE}.execute_db_queries") as mock_exec,
        patch(f"{MODULE}.RollupScoresSQL") as mock_rollup_cls,
        patch(f"{MODULE}.run_refresh_score_cards_results"),
    ):
        run_recalculate_project_scores("proj")

    mock_rollup_cls.assert_not_called()
    mock_exec.assert_not_called()


def test_table_group_with_profile_run_calls_profiling_rollup():
    run_id = uuid4()
    tg = _make_table_group(last_complete_profile_run_id=run_id)

    mock_rollup = MagicMock()
    mock_rollup.rollup_profiling_scores.return_value = ["q1"]

    with (
        patch(f"{MODULE}.database_session", side_effect=[_make_db_ctx([tg]), _make_db_ctx([])]),
        patch(f"{MODULE}.execute_db_queries") as mock_exec,
        patch(f"{MODULE}.RollupScoresSQL", return_value=mock_rollup),
        patch(f"{MODULE}.run_refresh_score_cards_results"),
    ):
        run_recalculate_project_scores("proj")

    mock_rollup.rollup_profiling_scores.assert_called_once()
    mock_exec.assert_called_once_with(["q1"])


def test_one_test_suite_calls_rollup_with_update_table_group_true():
    tg = _make_table_group()
    ts = _make_test_suite()

    mock_rollup = MagicMock()
    mock_rollup.rollup_profiling_scores.return_value = []
    mock_rollup.rollup_test_scores.return_value = ["q2"]

    with (
        patch(f"{MODULE}.database_session", side_effect=[_make_db_ctx([tg]), _make_db_ctx([ts])]),
        patch(f"{MODULE}.execute_db_queries"),
        patch(f"{MODULE}.RollupScoresSQL", return_value=mock_rollup),
        patch(f"{MODULE}.run_refresh_score_cards_results"),
    ):
        run_recalculate_project_scores("proj")

    mock_rollup.rollup_test_scores.assert_called_once_with(update_table_group=True)


def test_multiple_test_suites_only_last_has_update_table_group_true():
    tg = _make_table_group()
    ts1 = _make_test_suite()
    ts2 = _make_test_suite()

    mock_rollup = MagicMock()
    mock_rollup.rollup_profiling_scores.return_value = []
    mock_rollup.rollup_test_scores.return_value = []

    with (
        patch(f"{MODULE}.database_session", side_effect=[_make_db_ctx([tg]), _make_db_ctx([ts1, ts2])]),
        patch(f"{MODULE}.execute_db_queries"),
        patch(f"{MODULE}.RollupScoresSQL", return_value=mock_rollup),
        patch(f"{MODULE}.run_refresh_score_cards_results"),
    ):
        run_recalculate_project_scores("proj")

    calls = mock_rollup.rollup_test_scores.call_args_list
    assert calls == [
        call(update_table_group=False),
        call(update_table_group=True),
    ]


def test_refresh_always_called_at_end():
    tg = _make_table_group(last_complete_profile_run_id=uuid4())
    ts = _make_test_suite()
    mock_rollup = MagicMock()
    mock_rollup.rollup_profiling_scores.return_value = []
    mock_rollup.rollup_test_scores.return_value = []

    with (
        patch(f"{MODULE}.database_session", side_effect=[_make_db_ctx([tg]), _make_db_ctx([ts])]),
        patch(f"{MODULE}.execute_db_queries"),
        patch(f"{MODULE}.RollupScoresSQL", return_value=mock_rollup),
        patch(f"{MODULE}.run_refresh_score_cards_results") as mock_refresh,
    ):
        run_recalculate_project_scores("proj")

    mock_refresh.assert_called_once_with(project_code="proj")
