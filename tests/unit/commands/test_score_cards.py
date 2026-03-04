from uuid import uuid4

import pytest

from testgen.commands.run_refresh_score_cards_results import _score_card_to_results

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
