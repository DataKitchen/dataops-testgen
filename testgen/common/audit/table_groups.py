from collections.abc import Iterable

from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.audit.safety import never_raises
from testgen.common.audit.scorecards import record_scorecard_created, scorecard_changes
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup


@never_raises()
def record_table_group_created(table_group: TableGroup, scorecard: ScoreDefinition | None = None) -> None:
    """Record a new table group, and the scorecard created with it, each as its own record."""
    record(AuditAction.TABLE_GROUP_CREATED, table_group)
    if scorecard is not None:
        record_scorecard_created(scorecard)


@never_raises()
def record_table_group_updated(table_group: TableGroup, scorecards: Iterable[ScoreDefinition] = ()) -> None:
    """Record a table group's changes, and those of the scorecards its rename changed, each as its own record.

    Call it before the scorecards are flushed: a flush clears their pending changes.
    """
    scorecard_records = [(scorecard, scorecard_changes(scorecard)) for scorecard in scorecards]
    record(AuditAction.TABLE_GROUP_UPDATED, table_group)
    for scorecard, changes in scorecard_records:
        record(AuditAction.SCORECARD_UPDATED, scorecard, changes=changes)


@never_raises()
def record_table_group_deleted(table_group: TableGroup, scorecards: Iterable[ScoreDefinition] = ()) -> None:
    """Record a deleted table group, and the scorecards deleted with it, each as its own record."""
    record(AuditAction.TABLE_GROUP_DELETED, table_group)
    for scorecard in scorecards:
        record(AuditAction.SCORECARD_DELETED, scorecard)
