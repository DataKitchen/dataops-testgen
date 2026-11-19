"""Scorecards that follow a table group through a rename, and the ones created with it."""

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from testgen.common.audit.table_groups import record_table_group_updated
from testgen.common.models import Base
from testgen.common.models.scores import (
    ScoreCategory,
    ScoreDefinition,
    ScoreDefinitionBreakdownItem,
    ScoreDefinitionCriteria,
    ScoreDefinitionFilter,
    ScoreDefinitionResult,
    ScoreDefinitionResultHistoryEntry,
)
from testgen.common.models.table_group import TableGroup

pytestmark = pytest.mark.unit

SCORE_TABLES = [
    ScoreDefinition.__table__,
    ScoreDefinitionCriteria.__table__,
    ScoreDefinitionFilter.__table__,
    ScoreDefinitionResult.__table__,
    ScoreDefinitionBreakdownItem.__table__,
    ScoreDefinitionResultHistoryEntry.__table__,
]


@pytest.fixture
def session(audit_session):
    Base.metadata.create_all(audit_session.get_bind(), tables=SCORE_TABLES)
    return audit_session


def _created_with(name: str, project_code: str = "demo") -> ScoreDefinition:
    return ScoreDefinition.from_table_group(TableGroup(project_code=project_code, table_groups_name=name))


def _scorecard(name: str, filters: list[dict], group_by_field: bool = True) -> ScoreDefinition:
    scorecard = ScoreDefinition(project_code="demo", name=name, total_score=True, cde_score=False)
    scorecard.criteria = ScoreDefinitionCriteria.from_filters(filters, group_by_field=group_by_field)
    return scorecard


def _save(session, *scorecards: ScoreDefinition) -> None:
    session.add_all(scorecards)
    session.flush()


def _values(scorecard: ScoreDefinition) -> list[dict]:
    return sorted(scorecard.criteria, key=lambda item: item["value"])


def test_finds_only_scorecards_shaped_as_the_one_created_with_the_table_group(session):
    created = _created_with("sales")
    renamed_by_user = _created_with("sales")
    renamed_by_user.name = "Sales KPIs"
    with_more_filters = _scorecard(
        "sales", [{"field": "table_groups_name", "value": "sales"}, {"field": "data_source", "value": "ERP"}],
    )
    with_chain = _scorecard(
        "sales",
        [{"field": "table_groups_name", "value": "sales", "others": [{"field": "table_name", "value": "orders"}]}],
        group_by_field=False,
    )
    other_project = _created_with("sales", project_code="other")
    _save(session, created, renamed_by_user, with_more_filters, with_chain, other_project)

    assert ScoreDefinition.created_with_table_group("demo", "sales") == [created]


def test_rename_rewrites_every_filter_and_renames_only_the_scorecard_created_with_it(session):
    created = _created_with("sales")
    user_named = _scorecard("Revenue", [{"field": "table_groups_name", "value": "sales"}])
    chained = _scorecard(
        "Orders",
        [
            {"field": "table_groups_name", "value": "sales", "others": [{"field": "table_name", "value": "orders"}]},
            {"field": "table_groups_name", "value": "finance"},
        ],
        group_by_field=False,
    )
    unrelated = _created_with("finance")
    _save(session, created, user_named, chained, unrelated)

    renamed = ScoreDefinition.rename_table_group("demo", "sales", "sales_dw")
    session.flush()

    assert set(renamed) == {created, user_named, chained}
    assert (created.name, user_named.name, chained.name, unrelated.name) == ("sales_dw", "Revenue", "Orders", "finance")
    assert _values(created) == [{"field": "table_groups_name", "value": "sales_dw", "others": []}]
    assert _values(chained) == [
        {"field": "table_groups_name", "value": "finance", "others": []},
        {"field": "table_groups_name", "value": "sales_dw", "others": [{"field": "table_name", "value": "orders"}]},
    ]
    assert (chained.criteria.operand, chained.criteria.group_by_field) == ("OR", False)
    assert _values(unrelated) == [{"field": "table_groups_name", "value": "finance", "others": []}]
    assert ScoreDefinition.created_with_table_group("demo", "sales_dw") == [created]


def test_rename_relabels_the_cached_results_and_breakdowns_and_keeps_history(session):
    created = _created_with("sales")
    by_table_group = _scorecard("All groups", [{"field": "data_source", "value": "ERP"}])
    by_table_group.category = ScoreCategory.table_groups_name
    _save(session, created, by_table_group)
    run_time = datetime(2026, 11, 1)
    session.add_all([
        ScoreDefinitionResult(definition_id=created.id, category="score", score=0.9),
        ScoreDefinitionResult(definition_id=by_table_group.id, category="sales", score=0.8),
        ScoreDefinitionResult(definition_id=by_table_group.id, category="finance", score=0.7),
        ScoreDefinitionBreakdownItem(
            definition_id=by_table_group.id, category="table_groups_name", score_type="score",
            table_groups_name="sales", score=0.8,
        ),
        ScoreDefinitionResultHistoryEntry(
            definition_id=created.id, category="score", score=0.9, last_run_time=run_time,
        ),
    ])
    session.flush()

    ScoreDefinition.rename_table_group("demo", "sales", "sales_dw")
    session.flush()

    results = session.execute(
        select(ScoreDefinitionResult.category).where(ScoreDefinitionResult.definition_id == by_table_group.id)
    ).scalars().all()
    assert sorted(results) == ["finance", "sales_dw"]
    assert session.scalars(select(ScoreDefinitionBreakdownItem.table_groups_name)).all() == ["sales_dw"]
    assert session.scalars(select(ScoreDefinitionResultHistoryEntry.score)).all() == [0.9]


def test_rename_onto_the_name_of_a_deleted_table_group_replaces_its_cached_rows(session):
    by_table_group = _scorecard("All groups", [{"field": "data_source", "value": "ERP"}])
    by_table_group.category = ScoreCategory.table_groups_name
    _save(session, by_table_group)
    session.add_all([
        ScoreDefinitionResult(definition_id=by_table_group.id, category="sales", score=0.5),
        ScoreDefinitionResult(definition_id=by_table_group.id, category="sales_v2", score=0.8),
        ScoreDefinitionBreakdownItem(
            definition_id=by_table_group.id, category="table_groups_name", score_type="score",
            table_groups_name="sales", score=0.5,
        ),
        ScoreDefinitionBreakdownItem(
            definition_id=by_table_group.id, category="table_groups_name", score_type="score",
            table_groups_name="sales_v2", score=0.8,
        ),
    ])
    session.flush()

    ScoreDefinition.rename_table_group("demo", "sales_v2", "sales")
    session.flush()

    assert session.execute(select(ScoreDefinitionResult.category, ScoreDefinitionResult.score)).all() == [("sales", 0.8)]
    assert session.execute(
        select(ScoreDefinitionBreakdownItem.table_groups_name, ScoreDefinitionBreakdownItem.score)
    ).all() == [("sales", 0.8)]


def test_rename_records_each_changed_scorecard(session, audit_log):
    created = _created_with("sales")
    table_group = TableGroup(id=uuid4(), project_code="demo", table_groups_name="sales_dw")
    _save(session, created)
    session.commit()

    scorecards = ScoreDefinition.rename_table_group("demo", "sales", "sales_dw")
    record_table_group_updated(table_group, scorecards)
    session.commit()

    [entry] = [entry for entry in audit_log.records() if entry["action"] == "scorecard.updated"]
    assert entry["target_name"] == "sales_dw"
    assert entry["changes"]["name"] == {"from": "sales", "to": "sales_dw"}
    assert entry["changes"]["criteria"]["from"]["filters"][0]["value"] == "sales"
    assert entry["changes"]["criteria"]["to"]["filters"][0]["value"] == "sales_dw"


def test_filter_values_are_quoted_as_sql_literals():
    scorecard = _scorecard("O'Brien", [{"field": "table_groups_name", "value": "O'Brien"}])

    assert scorecard.criteria.get_as_sql() == "(table_groups_name = 'O''Brien')"
