import json
from typing import Any

from sqlalchemy.orm.attributes import PASSIVE_NO_INITIALIZE, get_history

from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import changes_of, created_changes, record
from testgen.common.audit.safety import never_raises
from testgen.common.models.scores import ScoreDefinition, ScoreDefinitionCriteria


@never_raises(dict)
def scorecard_changes(score_definition: ScoreDefinition) -> dict[str, dict[str, Any]]:
    """The changes to the scorecard's fields and filters that are not yet saved, the filters as ``criteria``.

    Read them before the scorecard is saved: saving it clears them.
    """
    changes = changes_of(score_definition)
    history = get_history(score_definition, "criteria", passive=PASSIVE_NO_INITIALIZE)
    if history.added:
        change = {"to": _criteria_value(history.added[0])}
        if history.deleted:
            change["from"] = _criteria_value(history.deleted[0])
        changes["criteria"] = change
    return changes


@never_raises()
def record_scorecard_created(score_definition: ScoreDefinition) -> None:
    """Record a saved new scorecard with the values and filters it holds."""
    changes = created_changes(score_definition) | {"criteria": {"to": _criteria_value(score_definition.criteria)}}
    record(AuditAction.SCORECARD_CREATED, score_definition, changes=changes)


def _criteria_value(criteria: ScoreDefinitionCriteria | None) -> dict[str, Any] | None:
    if criteria is None:
        return None
    filters = sorted(criteria, key=lambda item: json.dumps(item, sort_keys=True))
    return {"filters": filters, "group_by_field": criteria.group_by_field}
