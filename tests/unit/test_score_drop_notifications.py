from itertools import chain
from unittest.mock import ANY, call, patch

import pytest

from testgen.common.models.notification_settings import ScoreDropNotificationSettings
from testgen.common.models.scores import ScoreDefinition, ScoreDefinitionResult
from testgen.common.notifications.score_drop import collect_score_notification_data, send_score_drop_notifications


def create_ns(**kwargs):
    with patch("testgen.common.notifications.score_drop.ScoreDropNotificationSettings.save"):
        return ScoreDropNotificationSettings.create("proj", **kwargs)


@pytest.fixture
def ns_select_result():
    return [
        create_ns(
            recipients=["cde_99@example.com"],
            score_definition_id="sd-1",
            total_score_threshold=None,
            cde_score_threshold=99,
        ),
        create_ns(
            recipients=["total_99@example.com"],
            score_definition_id="sd-1",
            total_score_threshold=99,
            cde_score_threshold=None,
        ),
        create_ns(
            recipients=["both_97@example.com"],
            score_definition_id="sd-1",
            total_score_threshold=97,
            cde_score_threshold=97,
        ),
        create_ns(
            recipients=["both_94@example.com"],
            score_definition_id="sd-1",
            total_score_threshold=94,
            cde_score_threshold=94,
        ),
    ]

@pytest.fixture
def send_mock():
    with patch("testgen.common.notifications.score_drop.ScoreDropEmailTemplate.send") as mock:
        yield mock


@pytest.fixture
def db_session_mock():
    with patch("testgen.common.notifications.score_drop.get_current_session") as mock:
        yield mock


@pytest.fixture
def select_mock():
    with patch("testgen.common.notifications.score_drop.select") as mock:
        yield mock


@pytest.fixture
def score_definition():

    def result_list(sd):
        return [
            ScoreDefinitionResult(definition_id=sd.id, score=0.98, category=cat)
            for cat in chain(
                ("Uniqueness", "Accuracy", "Consistency"),
                ["cde_score"] if sd.cde_score else [],
                ["score"] if sd.total_score else [],
            )
        ]

    with patch.object(ScoreDefinition, "results", new=property(result_list)):
        sd = ScoreDefinition(
            id="sd-1",
            project_code="test-proj",
            name="My Score",
            cde_score=True,
            total_score=True,
        )
        yield sd


@pytest.mark.parametrize(
    "def_total, def_cde, fresh_total, fresh_cde, expected_categories",
    (
        (True, True, 0.99, 0.99, ["score", "cde_score"]),
        (True, False, 0.99, 0.99, ["score"]),
        (True, True, None, 0.99, ["cde_score"]),
        (True, False, None, 0.99, []),
    ),
)
def test_collect_score_notification_data(
    def_total, def_cde, fresh_total, fresh_cde, expected_categories, score_definition
):
    score_definition.total_score = def_total
    score_definition.cde_score = def_cde
    fresh_score = {"score": fresh_total, "cde_score": fresh_cde, "Accuracy": 0.99, "SomethingElse": 0.99}

    data = []
    collect_score_notification_data(data, score_definition, fresh_score)

    assert len(data) == len(expected_categories)
    data_per_category = {d[1]: d for d in data}
    for cat in expected_categories:
        sd, cat_data, prev, fresh = data_per_category[cat]
        assert sd == score_definition
        assert cat_data == cat
        assert prev == 0.98
        assert fresh == 0.99


def test_send_score_drop_notifications_no_data(select_mock):
    send_score_drop_notifications([])
    select_mock.assert_not_called()


def test_send_score_drop_notifications_no_match(
    score_definition, select_mock, db_session_mock, ns_select_result, send_mock,
):
    data = [
        (score_definition, "score", 1.0, 0.1),
        (score_definition, "cde_score", 1.0, 0.1)
    ]
    for ns in ns_select_result:
        ns.score_definition_id = "sd-x"
    db_session_mock().scalars.return_value = ns_select_result

    send_score_drop_notifications(data)

    send_mock.assert_not_called()


@pytest.mark.parametrize(
    "total_prev, total_fresh, cde_prev, cde_fresh, triggers",
    (
        (1.00, 0.99, 1.00, 0.99, ()),
        (0.92, 0.99, 0.92, 0.99, ()),
        (1.00, 1.00, 1.00, 0.98, ((False, True),)),
        (1.00, 0.98, 1.00, 1.00, ((True, False),)),
        (1.00, 0.98, 1.00, 0.98, ((False, True), (True, False))),
        (1.00, 0.97, 1.00, 0.97, ((False, True), (True, False))),
        (1.00, 0.96, 1.00, 0.96, ((False, True), (True, False), (True, True))),
        (1.00, 0.94, 1.00, 0.94, ((False, True), (True, False), (True, True))),
        (1.00, 0.93, 1.00, 0.93, ((False, True), (True, False), (True, True), (True, True))),
        (0.89, 0.82, 0.87, 0.82, ((False, True), (True, False), (True, True), (True, True))),
    )
)
def test_send_score_drop_notifications(
    total_prev, total_fresh, cde_prev, cde_fresh, triggers, score_definition, db_session_mock, ns_select_result,
    send_mock,
):
    data = [
        (score_definition, "score", total_prev, total_fresh),
        (score_definition, "cde_score", cde_prev, cde_fresh)
    ]
    db_session_mock().scalars.return_value = ns_select_result

    send_score_drop_notifications(data)

    expected_total_diff = {
        "category": "score", "label": "Total", "prev": total_prev, "current": total_fresh, "threshold": ANY,
    }
    expected_cde_diff = {
        "category": "cde_score", "label": "CDE", "prev": cde_prev, "current": cde_fresh, "threshold": ANY,
    }
    send_mock.assert_has_calls(
        [
            call(
                [ANY],
                {
                    "definition": score_definition,
                    "definition_url": "http://localhost:8501/quality-dashboard:score-details?definition_id=sd-1",
                    "diff": [
                        {**expected_total_diff, "notify": total_triggers},
                        {**expected_cde_diff, "notify": cde_triggers},
                    ]
                }
            )
            for total_triggers, cde_triggers in triggers
        ]
    )
    assert send_mock.call_count == len(triggers)
