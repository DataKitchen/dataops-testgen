from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.commands.run_refresh_score_cards_results import (
    _score_card_to_results,
    save_and_refresh_score_definition,
)
from testgen.common.models.scores import ScoreDefinition, ScoreDefinitionCriteria

pytestmark = pytest.mark.unit


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


def test_save_and_refresh_score_definition_for_existing_card_calls_save_refresh_and_recalculate():
    """is_new=False path: save → refresh → recalculate, all in that order."""
    sd = _fake_definition()
    call_order: list[str] = []

    def record(name):
        def _called(*_a, **_kw):
            call_order.append(name)
        return _called

    with (
        patch.object(ScoreDefinition, "save", autospec=True, side_effect=record("save")),
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_refresh_score_cards_results",
            side_effect=record("refresh"),
        ),
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_recalculate_score_card",
            side_effect=record("recalculate"),
        ),
    ):
        save_and_refresh_score_definition(sd, is_new=False)

    assert call_order == ["save", "refresh", "recalculate"]


def test_save_and_refresh_score_definition_for_existing_card_passes_refresh_kwargs_for_update():
    """Updates (is_new=False) do NOT pass add_history_entry / refresh_date."""
    sd = _fake_definition()

    with (
        patch.object(ScoreDefinition, "save", autospec=True),
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_refresh_score_cards_results",
        ) as mock_refresh,
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_recalculate_score_card",
        ),
    ):
        save_and_refresh_score_definition(sd, is_new=False)

    mock_refresh.assert_called_once_with(definition_id=sd.id)


def test_save_and_refresh_score_definition_for_new_card_skips_recalculate():
    """is_new=True path: save → refresh with history kwargs; no recalculate."""
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
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_recalculate_score_card",
        ) as mock_recalc,
    ):
        save_and_refresh_score_definition(sd, is_new=True)

    mock_refresh.assert_called_once_with(
        definition_id=sd.id,
        add_history_entry=True,
        refresh_date=fake_latest.run_time,
    )
    mock_recalc.assert_not_called()


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
        patch(
            "testgen.commands.run_refresh_score_cards_results.run_recalculate_score_card",
        ),
    ):
        save_and_refresh_score_definition(sd, is_new=True)

    mock_refresh.assert_called_once_with(
        definition_id=sd.id,
        add_history_entry=True,
        refresh_date=None,
    )
