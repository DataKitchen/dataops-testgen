from collections import defaultdict
from collections.abc import Callable, Collection, Hashable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from testgen.common.audit.actions import AuditAction, AuditTargetType
from testgen.common.audit.recorder import record
from testgen.common.audit.safety import never_raises


@dataclass(frozen=True)
class AuditedObject:
    """An object acted on as part of a selection, as its record names it."""

    id: UUID
    project_code: str | None
    name: str | None


@never_raises()
def record_selection(
    action: AuditAction,
    objects: Collection[AuditedObject],
    target_type: AuditTargetType,
    *,
    changes: dict[str, dict[str, Any]] | None = None,
    single_changes: Callable[[AuditedObject], dict[str, dict[str, Any]]] | None = None,
) -> None:
    """Record ``action`` on ``objects``, one record per project. An empty selection records nothing.

    :param changes: the changed fields a record of several objects carries.
    :param single_changes: builds the changed fields a record of one object carries instead, with its previous values.
    """
    by_project: dict[str | None, list[AuditedObject]] = defaultdict(list)
    for obj in objects:
        by_project[obj.project_code].append(obj)
    for project_code, project_objects in by_project.items():
        single = len(project_objects) == 1
        record(
            action,
            project_code=project_code,
            target_type=target_type,
            targets=[obj.id for obj in project_objects],
            target_name=project_objects[0].name if single else None,
            changes=(single_changes(project_objects[0]) if single and single_changes else changes) or {},
        )


def common_changes(per_object: Collection[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """The fields every object changed to the same new value, as a record of several objects writes them.

    A field withheld or holding a value that can't be compared this way, such as a JSON document, is left out.
    """
    values: dict[str, set[Any]] = defaultdict(set)
    counts: dict[str, int] = defaultdict(int)
    for changes in per_object:
        for name, entry in changes.items():
            counts[name] += 1
            if "to" in entry and isinstance(entry["to"], Hashable):
                values[name].add(entry["to"])
    return {
        name: {"to": next(iter(found))}
        for name, found in values.items()
        if len(found) == 1 and counts[name] == len(per_object)
    }
