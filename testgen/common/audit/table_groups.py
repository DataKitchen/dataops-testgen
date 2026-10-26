from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.audit.safety import never_raises
from testgen.common.audit.scorecards import record_scorecard_created
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup


@never_raises()
def record_table_group_created(table_group: TableGroup, scorecard: ScoreDefinition | None = None) -> None:
    """Record a new table group, and the scorecard created with it, each as its own record."""
    record(AuditAction.TABLE_GROUP_CREATED, table_group)
    if scorecard is not None:
        record_scorecard_created(scorecard)

