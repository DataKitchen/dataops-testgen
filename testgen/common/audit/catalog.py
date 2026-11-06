from collections import defaultdict
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import changes_of, record
from testgen.common.audit.safety import isolated_read, never_raises
from testgen.common.audit.selections import common_changes
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.data_table import DataTable
from testgen.common.models.table_group import TableGroup

_ACTIONS = {
    DataTable: AuditAction.CATALOG_TABLE_UPDATED,
    DataColumnChars: AuditAction.CATALOG_COLUMN_UPDATED,
}


@never_raises()
def record_catalog_changes(entries: Iterable[DataTable | DataColumnChars]) -> None:
    """Record the metadata changed on data catalog tables and columns, as one act.

    Each kind of entry, in each project, gets one record: a single entry with its previous and new values, several
    with the new values they all share. Entries whose metadata did not change are left out.
    """
    changed: dict[tuple[type, str | None], list[tuple[DataTable | DataColumnChars, dict[str, dict[str, Any]]]]]
    changed = defaultdict(list)
    entries = list(dict.fromkeys(entries))
    projects = _projects({entry.table_groups_id for entry in entries})
    for entry in entries:
        if changes := changes_of(entry):
            changed[(type(entry), projects.get(entry.table_groups_id))].append((entry, changes))
    for (kind, project_code), items in changed.items():
        action = _ACTIONS[kind]
        if len(items) == 1:
            entry, changes = items[0]
            record(action, entry, project_code=project_code, changes=changes)
        else:
            record(
                action,
                project_code=project_code,
                target_type=kind.__audit__.target_type,
                targets=[entry.id for entry, _ in items],
                changes=common_changes([changes for _, changes in items]),
            )


def _projects(table_group_ids: set[UUID]) -> dict[UUID, str]:
    if not table_group_ids:
        return {}
    with isolated_read() as session:
        rows = session.execute(
            select(TableGroup.id, TableGroup.project_code).where(TableGroup.id.in_(table_group_ids))
        )
        return {row.id: row.project_code for row in rows}
