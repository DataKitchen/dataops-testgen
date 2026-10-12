from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.run_refresh_score_cards_results import (
    _score_card_to_results,
    run_recalculate_score_card,
    run_refresh_score_cards_results,
    save_and_refresh_score_definition,
)
from testgen.common.enums import JobKey, JobSource
from testgen.common.models.scores import ScoreDefinition, ScoreDefinitionCriteria

pytestmark = pytest.mark.unit

REFRESH_MODULE = "testgen.commands.run_refresh_score_cards_results"


def _make_score_card(**overrides):
    defaults = {
        "id": str(uuid4()),
        "project_code": "test_project",
        "name": "Test Score Card",
        "score": 85.5,
        "cde_score": 90.0,
        "profiling_score": 80.0,
        "testing_score": 88.0,
        "categories": [],
        "history": [],
        "definition": None,
    }
    defaults.update(overrides)
    return defaults


def test_basic_result_count():
    """Should produce 4 base results (score, cde_score, profiling_score, testing_score)."""
    card = _make_score_card()
    results = _score_card_to_results(card)
    assert len(results) == 4


def test_result_categories():
    card = _make_score_card()
    results = _score_card_to_results(card)
    categories = [r.category for r in results]
    assert categories == ["score", "cde_score", "profiling_score", "testing_score"]


def test_result_scores_match_card():
    card = _make_score_card(score=85.5, cde_score=90.0, profiling_score=80.0, testing_score=88.0)
    results = _score_card_to_results(card)
    assert results[0].score == 85.5
    assert results[1].score == 90.0
    assert results[2].score == 80.0
    assert results[3].score == 88.0


def test_definition_id_set():
    card_id = str(uuid4())
    card = _make_score_card(id=card_id)
    results = _score_card_to_results(card)
    for result in results:
        assert str(result.definition_id) == card_id


def test_with_categories():
    """Categories from score card should be appended as extra results."""
    card = _make_score_card(categories=[
        {"label": "completeness", "score": 95.0},
        {"label": "accuracy", "score": 72.0},
    ])
    results = _score_card_to_results(card)
    assert len(results) == 6  # 4 base + 2 categories
    assert results[4].category == "completeness"
    assert results[4].score == 95.0
    assert results[5].category == "accuracy"
    assert results[5].score == 72.0


def test_empty_categories():
    card = _make_score_card(categories=[])
    results = _score_card_to_results(card)
    assert len(results) == 4


def test_none_score_values():
    card = _make_score_card(score=None, cde_score=None, profiling_score=None, testing_score=None)
    results = _score_card_to_results(card)
    for result in results:
        assert result.score is None


# --- save_and_refresh_score_definition ---


def _fake_definition(project_code: str = "demo") -> ScoreDefinition:
    sd = ScoreDefinition()
    sd.id = uuid4()
    sd.project_code = project_code
    sd.name = "Card"
    sd.total_score = True
    sd.cde_score = False
    sd.category = None
    sd.criteria = ScoreDefinitionCriteria.from_filters(
        [{"field": "table_groups_name", "value": "tg1"}],
        group_by_field=True,
    )
    return sd


def test_save_and_refresh_score_definition_for_existing_card_queues_the_history_recalculation():
    """is_new=False path: save → commit → refresh → queue the history recalculation, in that order.

    The save commits before the refresh, which rolls back a scorecard it fails on.
    """
    sd = _fake_definition()
    call_order: list[str] = []

    def record(name):
        def _called(*_a, **_kw):
            call_order.append(name)
        return _called

    with (
        patch(f"{REFRESH_MODULE}.get_current_session") as mock_session,
        patch.object(ScoreDefinition, "save", autospec=True, side_effect=record("save")),
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_refresh_score_cards_results",
            side_effect=record("refresh"),
        ),
        patch(
            "testgen.commands.run_refresh_score_cards_results.JobExecution.submit",
            side_effect=record("submit"),
        ) as mock_submit,
    ):
        mock_session.return_value.commit.side_effect = record("commit")
        save_and_refresh_score_definition(sd, is_new=False, source=JobSource.ui)

    assert call_order == ["save", "commit", "refresh", "submit"]
    mock_submit.assert_called_once_with(
        job_key=JobKey.recalculate_score_card,
        kwargs={"project_code": "demo", "definition_id": str(sd.id)},
        source=JobSource.ui,
        project_code="demo",
    )


def test_save_and_refresh_score_definition_for_existing_card_passes_refresh_kwargs_for_update():
    """Updates (is_new=False) do NOT pass add_history_entry / refresh_date."""
    sd = _fake_definition()

    with (
        patch.object(ScoreDefinition, "save", autospec=True),
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_refresh_score_cards_results",
        ) as mock_refresh,
        patch("testgen.commands.run_refresh_score_cards_results.JobExecution.submit"),
    ):
        save_and_refresh_score_definition(sd, is_new=False, source=JobSource.ui)

    mock_refresh.assert_called_once_with(definition_id=sd.id)


def test_save_and_refresh_score_definition_for_new_card_skips_recalculate():
    """is_new=True path: save → refresh with history kwargs; no recalculation queued."""
    sd = _fake_definition()

    fake_latest = type("Run", (), {"run_time": datetime(2026, 5, 1, tzinfo=UTC)})()

    with (
        patch.object(ScoreDefinition, "save", autospec=True),
        patch(
            "testgen.commands.run_refresh_score_cards_results.ProfilingRun.get_latest_run",
            return_value=fake_latest,
        ),
        patch(
            "testgen.commands.run_refresh_score_cards_results.TestRun.get_latest_run",
            return_value=None,
        ),
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_refresh_score_cards_results",
        ) as mock_refresh,
        patch("testgen.commands.run_refresh_score_cards_results.JobExecution.submit") as mock_submit,
    ):
        save_and_refresh_score_definition(sd, is_new=True, source=JobSource.ui)

    mock_refresh.assert_called_once_with(
        definition_id=sd.id,
        add_history_entry=True,
        refresh_date=fake_latest.run_time,
    )
    mock_submit.assert_not_called()


def test_save_and_refresh_score_definition_for_new_card_handles_no_runs():
    """When there are no profiling/test runs for the project, refresh_date is None."""
    sd = _fake_definition()

    with (
        patch.object(ScoreDefinition, "save", autospec=True),
        patch(
            "testgen.commands.run_refresh_score_cards_results.ProfilingRun.get_latest_run",
            return_value=None,
        ),
        patch(
            "testgen.commands.run_refresh_score_cards_results.TestRun.get_latest_run",
            return_value=None,
        ),
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_refresh_score_cards_results",
        ) as mock_refresh,
        patch("testgen.commands.run_refresh_score_cards_results.JobExecution.submit"),
    ):
        save_and_refresh_score_definition(sd, is_new=True, source=JobSource.ui)

    mock_refresh.assert_called_once_with(
        definition_id=sd.id,
        add_history_entry=True,
        refresh_date=None,
    )



def _refresh_project(definitions: list) -> None:
    with (
        patch(f"{REFRESH_MODULE}.ScoreDefinition.all", return_value=definitions),
        patch(f"{REFRESH_MODULE}._score_card_to_results", return_value=[]),
        patch(f"{REFRESH_MODULE}._score_definition_to_results_breakdown", return_value=[]),
        patch(f"{REFRESH_MODULE}.collect_score_notification_data"),
        patch(f"{REFRESH_MODULE}.send_score_drop_notifications"),
    ):
        run_refresh_score_cards_results(project_code="test_project")


def test_each_refreshed_scorecard_commits_on_its_own(db_session_mock):
    steps = MagicMock()
    first, second = MagicMock(name="first"), MagicMock(name="second")
    steps.attach_mock(first.save, "save_first")
    steps.attach_mock(second.save, "save_second")
    steps.attach_mock(db_session_mock.commit, "commit")

    _refresh_project([first, second])

    # The session the refresh opened commits once more on its way out.
    assert [name for name, *_ in steps.mock_calls][:4] == ["save_first", "commit", "save_second", "commit"]


def test_a_failed_scorecard_is_rolled_back_and_the_next_still_commits(db_session_mock):
    failing, healthy = MagicMock(name="failing"), MagicMock(name="healthy")
    failing.as_score_card.side_effect = RuntimeError("boom")

    _refresh_project([failing, healthy])

    db_session_mock.rollback.assert_called_once()
    healthy.save.assert_called_once()
    assert db_session_mock.commit.call_count >= 1


def test_recalculating_a_missing_scorecard_raises(db_session_mock):
    with (
        patch(f"{REFRESH_MODULE}.ScoreDefinition.get", return_value=None),
        pytest.raises(ValueError, match="Scorecard missing-id not found"),
    ):
        run_recalculate_score_card(project_code="demo", definition_id="missing-id")


def test_a_scorecard_is_locked_after_computing_and_before_its_rows_are_replaced(db_session_mock):
    definition = MagicMock(name="definition")
    steps = MagicMock()
    steps.attach_mock(definition.as_score_card, "compute")
    steps.attach_mock(definition.lock_for_refresh, "lock")
    steps.attach_mock(definition.clear_results, "clear")
    steps.attach_mock(definition.save, "save")
    with (
        patch(f"{REFRESH_MODULE}.ScoreDefinition.all", return_value=[definition]),
        patch(f"{REFRESH_MODULE}._score_card_to_results", return_value=[]),
        patch(f"{REFRESH_MODULE}._score_definition_to_results_breakdown", side_effect=lambda _: steps.breakdown()),
        patch(f"{REFRESH_MODULE}.collect_score_notification_data"),
        patch(f"{REFRESH_MODULE}.send_score_drop_notifications"),
    ):
        run_refresh_score_cards_results(project_code="test_project")

    assert [name for name, *_ in steps.mock_calls if name in {"compute", "breakdown", "lock", "clear", "save"}] == [
        "compute", "breakdown", "lock", "clear", "save",
    ]


def test_a_scorecard_whose_lock_times_out_is_rolled_back_and_the_next_still_refreshes(db_session_mock):
    locked, free = MagicMock(name="locked"), MagicMock(name="free")
    locked.lock_for_refresh.side_effect = RuntimeError("canceling statement due to lock timeout")

    _refresh_project([locked, free])

    locked.clear_results.assert_not_called()
    db_session_mock.rollback.assert_called_once()
    free.save.assert_called_once()


def test_score_drops_are_checked_under_the_lock_and_sent_only_for_committed_scorecards(db_session_mock):
    locked, free = MagicMock(name="locked"), MagicMock(name="free")
    locked.lock_for_refresh.side_effect = RuntimeError("canceling statement due to lock timeout")
    steps = MagicMock()
    steps.attach_mock(free.lock_for_refresh, "lock")
    steps.attach_mock(db_session_mock.refresh, "reread")
    with (
        patch(f"{REFRESH_MODULE}.ScoreDefinition.all", return_value=[locked, free]),
        patch(f"{REFRESH_MODULE}._score_card_to_results", return_value=[]),
        patch(f"{REFRESH_MODULE}._score_definition_to_results_breakdown", return_value=[]),
        patch(
            f"{REFRESH_MODULE}.collect_score_notification_data",
            side_effect=lambda data, definition, _: (steps.collect(), data.append(definition)),
        ),
        patch(f"{REFRESH_MODULE}.send_score_drop_notifications") as send,
    ):
        run_refresh_score_cards_results(project_code="test_project")

    assert [name for name, *_ in steps.mock_calls] == ["lock", "reread", "collect"]
    send.assert_called_once_with([free])


def test_refresh_for_table_groups_skips_scorecards_that_cannot_include_them(db_session_mock):
    sales_card, finance_card = MagicMock(name="sales_card"), MagicMock(name="finance_card")
    sales_card.can_include_table_group.side_effect = lambda name: name == "sales"
    finance_card.can_include_table_group.side_effect = lambda name: name == "finance"
    table_group = MagicMock(table_groups_name="sales")
    with (
        patch(f"{REFRESH_MODULE}.ScoreDefinition.all", return_value=[sales_card, finance_card]),
        patch(f"{REFRESH_MODULE}.TableGroup.select_minimal_where", return_value=[table_group]),
        patch(f"{REFRESH_MODULE}._score_card_to_results", return_value=[]),
        patch(f"{REFRESH_MODULE}._score_definition_to_results_breakdown", return_value=[]),
        patch(f"{REFRESH_MODULE}.collect_score_notification_data"),
        patch(f"{REFRESH_MODULE}.send_score_drop_notifications"),
    ):
        run_refresh_score_cards_results(project_code="test_project", table_group_ids=[str(uuid4())])

    sales_card.save.assert_called_once()
    finance_card.save.assert_not_called()
