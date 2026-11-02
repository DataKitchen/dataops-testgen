from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from testgen.common.audit.actions import AuditAction, AuditTargetType
from testgen.common.audit.names import object_name
from testgen.common.audit.recorder import changes_of, changes_since, record
from testgen.common.audit.safety import never_raises
from testgen.common.audit.selections import AuditedObject, record_selection
from testgen.common.enums import MonitorType
from testgen.common.models import get_current_session
from testgen.common.models.test_definition import (
    AUDIT_PLACEMENT_FIELDS,
    AUDIT_STATE_FIELDS,
    TestDefinition,
    TestType,
)
from testgen.common.models.test_suite import TestSuite
from testgen.common.test_definition_export_import_service import (
    ImportAction,
    ImportConfig,
    ImportMode,
    ImportResponse,
)

_MONITOR_TYPES = frozenset(MonitorType)

_ACTIONS = {
    AuditTargetType.TEST_DEFINITION: {
        "created": AuditAction.TEST_DEFINITION_CREATED,
        "updated": AuditAction.TEST_DEFINITION_UPDATED,
        "deleted": AuditAction.TEST_DEFINITION_DELETED,
    },
    AuditTargetType.MONITOR: {
        "created": AuditAction.MONITOR_CREATED,
        "updated": AuditAction.MONITOR_UPDATED,
        "deleted": AuditAction.MONITOR_DELETED,
    },
}


@dataclass(frozen=True)
class AuditedTest(AuditedObject):
    """A test definition as its records name it."""

    test_suite_id: UUID | None = None
    table_groups_id: UUID | None = None
    is_monitor: bool = False


@never_raises(list)
def describe_tests(test_definition_ids: Iterable[UUID | str]) -> list[AuditedTest]:
    """The named test definitions, with the project and name their records carry. Never flushes the session."""
    ids = [UUID(str(identifier)) for identifier in test_definition_ids]
    if not ids:
        return []
    session = get_current_session()
    with session.no_autoflush:
        rows = session.execute(
            select(
                TestDefinition.id,
                TestDefinition.test_type,
                TestDefinition.table_name,
                TestDefinition.column_name,
                TestDefinition.test_suite_id,
                TestDefinition.table_groups_id,
                TestSuite.project_code,
                TestType.test_name_short,
            )
            .join(TestSuite, TestSuite.id == TestDefinition.test_suite_id)
            .outerjoin(TestType, TestType.test_type == TestDefinition.test_type)
            .where(TestDefinition.id.in_(ids))
        ).all()
    by_id = {
        row.id: AuditedTest(
            id=row.id,
            project_code=row.project_code,
            name=object_name(row.test_name_short or row.test_type, row.table_name, row.column_name),
            test_suite_id=row.test_suite_id,
            table_groups_id=row.table_groups_id,
            is_monitor=row.test_type in _MONITOR_TYPES,
        )
        for row in rows
    }
    return [by_id[identifier] for identifier in dict.fromkeys(ids) if identifier in by_id]


def record_tests(
    action: AuditAction,
    tests: Collection[AuditedTest],
    *,
    target_type: AuditTargetType = AuditTargetType.TEST_DEFINITION,
    changes: dict[str, dict[str, Any]] | None = None,
    single_changes: Callable[[AuditedObject], dict[str, dict[str, Any]]] | None = None,
) -> None:
    """Record ``action`` on ``tests``, one record per project. See ``record_selection``."""
    record_selection(action, tests, target_type, changes=changes, single_changes=single_changes)


@never_raises()
def record_status_changed(attribute: str, value: bool, test_definition_ids: Collection[UUID]) -> None:
    """Record the tests whose ``attribute`` (``test_active``, ``lock_refresh``, or ``flagged``) became ``value``.

    Switching a test on or off is ``enabled`` or ``disabled``; a lock or a flag is an update of the test's state.
    """
    tests = describe_tests(test_definition_ids)
    if attribute == "test_active":
        action = AuditAction.TEST_DEFINITION_ENABLED if value else AuditAction.TEST_DEFINITION_DISABLED
        record_tests(action, tests)
    else:
        record_tests(
            AuditAction.TEST_DEFINITION_UPDATED,
            tests,
            target_type=AuditTargetType.TEST_DEFINITION_STATE,
            changes={attribute: {"to": value}},
            single_changes=lambda _test: {attribute: {"from": not value, "to": value}},
        )


@never_raises()
def record_tests_moved(
    moving: Collection[AuditedTest],
    moved_ids: Collection[UUID],
    target_test_suite_id: UUID | str,
    target_table_group_id: UUID | str,
    target_table_name: str | None = None,
    target_column_name: str | None = None,
) -> None:
    """Record tests moved into a test suite: where they came from, when they shared it, and where they went.

    :param moving: the tests as they were before the move, as ``describe_tests`` read them.
    :param moved_ids: the rows the move wrote, which for a contract are its draft's copies.
    """
    changes: dict[str, dict[str, Any]] = {}
    for name, target, before in (
        ("test_suite_id", target_test_suite_id, {test.test_suite_id for test in moving}),
        ("table_groups_id", target_table_group_id, {test.table_groups_id for test in moving}),
    ):
        entry: dict[str, Any] = {"to": str(target)}
        if len(before) == 1 and (previous := next(iter(before))) is not None:
            entry = {"from": str(previous), **entry}
        if entry.get("from") != entry["to"]:
            changes[name] = entry
    if target_table_name:
        changes["table_name"] = {"to": target_table_name}
    if target_column_name:
        changes["column_name"] = {"to": target_column_name}

    by_id = {test.id: test for test in moving}
    projects = {test.project_code for test in moving}
    project_code = next(iter(projects)) if len(projects) == 1 else None
    moved = [by_id.get(identifier) or AuditedTest(id=identifier, project_code=project_code, name=None)
             for identifier in moved_ids]
    record_tests(
        AuditAction.TEST_DEFINITION_UPDATED, moved, target_type=AuditTargetType.TEST_DEFINITION_PLACEMENT,
        changes=changes,
    )


@never_raises()
def record_test_saved(definition: TestDefinition, *, created: bool, stored: Mapping[str, Any] | None = None) -> None:
    """Record a test definition, or a monitor, created or changed through a form or a tool.

    A test's update records its changed fields, then its lock or flag as an update of its state, and its switch on or
    off, each as its own record. A save that changed nothing records nothing.

    :param created: whether the save created the test.
    :param stored: the test's values as stored before the save, for an object built from a form rather than loaded;
        without it, the changes are read from the object's history.
    """
    is_monitor = definition.test_type in _MONITOR_TYPES
    target_type = AuditTargetType.MONITOR if is_monitor else AuditTargetType.TEST_DEFINITION
    actions = _ACTIONS[target_type]
    if created:
        record(actions["created"], definition, target_type=target_type)
        return

    changes = changes_of(definition) if stored is None else changes_since(definition, stored)
    for name in AUDIT_PLACEMENT_FIELDS:
        changes.pop(name, None)
    switched = None if is_monitor else changes.pop("test_active", None)
    state = {} if is_monitor else {name: changes.pop(name) for name in AUDIT_STATE_FIELDS if name in changes}
    if changes:
        record(actions["updated"], definition, target_type=target_type, changes=changes)
    if state:
        record(
            AuditAction.TEST_DEFINITION_UPDATED,
            definition,
            target_type=AuditTargetType.TEST_DEFINITION_STATE,
            changes=state,
        )
    if switched:
        action = AuditAction.TEST_DEFINITION_ENABLED if switched.get("to") else AuditAction.TEST_DEFINITION_DISABLED
        record(action, definition, changes={})


@never_raises()
def record_tests_deleted(tests: Collection[AuditedTest]) -> None:
    """Record ``tests`` deleted, the monitors among them as monitors.

    :param tests: the tests as they were before the deletion.
    """
    for is_monitor, target_type in ((False, AuditTargetType.TEST_DEFINITION), (True, AuditTargetType.MONITOR)):
        if group := [test for test in tests if test.is_monitor == is_monitor]:
            record_tests(_ACTIONS[target_type]["deleted"], group, target_type=target_type)


@never_raises()
def record_import(test_suite: TestSuite, config: ImportConfig, response: ImportResponse) -> None:
    """Record what an import of test definitions into ``test_suite`` did: the tests it created, updated, and deleted,
    each as one record. A preview records nothing, and a deleted test is no longer there to be named.
    """
    if config.mode == ImportMode.preview:
        return
    ids: dict[ImportAction, list[UUID]] = defaultdict(list)
    for item in response.items:
        ids[item.action].extend(td.target_id for td in item.tds if td.target_id is not None)
    record_tests(AuditAction.TEST_DEFINITION_CREATED, describe_tests(ids[ImportAction.create]))
    record_tests(AuditAction.TEST_DEFINITION_UPDATED, describe_tests(ids[ImportAction.update]))
    record_tests(
        AuditAction.TEST_DEFINITION_DELETED,
        [
            AuditedTest(id=identifier, project_code=test_suite.project_code, name=None, test_suite_id=test_suite.id)
            for identifier in dict.fromkeys(ids[ImportAction.delete])
        ],
    )
