"""The score-drop webhook payload must carry scores and threshold on one scale.

Scores are stored as 0-1 fractions; a rule's threshold is set as 0-100. The email
body multiplies scores by 100 before rendering, so it reads consistently. A
receiver written against the published ``data`` contract compares the two
directly, so the payload has to do the same normalization.
"""

import pytest

from testgen.common.notifications.score_drop import ScoreDropEmailTemplate

pytestmark = pytest.mark.unit


def _context():
    return {
        "project_name": "P",
        "definition": type("Definition", (), {"name": "Scorecard"})(),
        "diff": [
            {"label": "Total", "prev": 0.97, "current": 0.86, "threshold": 90.0, "notify": True},
            {"label": "CDE", "prev": 0.99, "current": 0.99, "threshold": 90.0, "notify": False},
        ],
    }


def test_scores_are_published_on_the_threshold_scale():
    categories = ScoreDropEmailTemplate().webhook_data(_context())["categories"]

    total, cde = categories
    assert (total["previous"], total["current"], total["threshold"]) == (97.0, 86.0, 90.0)
    assert (cde["previous"], cde["current"], cde["threshold"]) == (99.0, 99.0, 90.0)


def test_a_receiver_comparing_current_against_threshold_is_correct():
    """The obvious receiver rule must fire for the dropped category and no other.

    With scores left as fractions every category satisfies ``current < threshold``,
    so a receiver alerting on it fires on healthy scorecards too.
    """
    categories = ScoreDropEmailTemplate().webhook_data(_context())["categories"]

    fired = {c["label"] for c in categories if c["current"] < c["threshold"]}
    crossed = {c["label"] for c in categories if c["crossed"]}
    assert fired == crossed == {"Total"}


def test_missing_values_stay_none():
    context = _context()
    context["diff"] = [{"label": "Total", "prev": None, "current": None, "threshold": None, "notify": False}]

    category = ScoreDropEmailTemplate().webhook_data(context)["categories"][0]
    assert category["previous"] is None
    assert category["current"] is None
    assert category["threshold"] is None
