from collections.abc import Collection, Mapping
from uuid import UUID

from sqlalchemy import select

from testgen.common.audit.actions import AuditAction, AuditTargetType
from testgen.common.audit.names import object_name
from testgen.common.audit.safety import isolated_read, never_raises
from testgen.common.audit.selections import AuditedObject, record_selection
from testgen.common.audit.test_definitions import describe_tests, record_tests
from testgen.common.enums import Disposition
from testgen.common.models.hygiene_issue import HygieneIssue, HygieneIssueType
from testgen.common.models.test_definition import TestType
from testgen.common.models.test_result import TestResult
from testgen.common.models.test_suite import TestSuite
from testgen.common.test_result_disposition_service import DispositionUpdate, coupled_test_definition_state


@never_raises()
def record_result_dispositions(update: DispositionUpdate, disposition: Disposition | None) -> None:
    """Record a disposition set on test results: the results whose disposition changed, then their tests switched
    off or on, and locked or unlocked, with it.
    """
    _record_dispositions(
        AuditAction.TEST_RESULT_UPDATED,
        AuditTargetType.TEST_RESULT,
        _describe_results(update.changed),
        update.changed,
        disposition,
    )
    test_active, lock_refresh = coupled_test_definition_state(disposition)
    if update.switched:
        action = AuditAction.TEST_DEFINITION_ENABLED if test_active else AuditAction.TEST_DEFINITION_DISABLED
        record_tests(action, describe_tests(update.switched))
    if update.relocked:
        record_tests(
            AuditAction.TEST_DEFINITION_UPDATED,
            describe_tests(update.relocked),
            target_type=AuditTargetType.TEST_DEFINITION_STATE,
            changes={"lock_refresh": {"to": lock_refresh}},
            single_changes=lambda _test: {"lock_refresh": {"from": not lock_refresh, "to": lock_refresh}},
        )


@never_raises()
def record_issue_dispositions(previous: Mapping[UUID, str | None], disposition: str | None) -> None:
    """Record ``disposition`` set on hygiene issues, for those whose disposition it changed.

    :param previous: each issue's disposition before the change.
    """
    changed = {issue_id: value for issue_id, value in previous.items() if value != disposition}
    _record_dispositions(
        AuditAction.HYGIENE_ISSUE_UPDATED,
        AuditTargetType.HYGIENE_ISSUE,
        _describe_issues(changed),
        changed,
        disposition,
    )


def _record_dispositions(
    action: AuditAction,
    target_type: AuditTargetType,
    objects: Collection[AuditedObject],
    previous: Mapping[UUID, str | None],
    disposition: str | None,
) -> None:
    new_value = str(disposition) if disposition is not None else None
    record_selection(
        action,
        objects,
        target_type,
        changes={"disposition": {"to": new_value}},
        single_changes=lambda obj: {"disposition": {"from": previous[obj.id], "to": new_value}},
    )


def _describe_results(result_ids: Collection[UUID]) -> list[AuditedObject]:
    if not result_ids:
        return []
    with isolated_read() as session:
        rows = session.execute(
            select(
                TestResult.id,
                TestResult.test_type,
                TestResult.table_name,
                TestResult.column_names,
                TestSuite.project_code,
                TestType.test_name_short,
            )
            .join(TestSuite, TestSuite.id == TestResult.test_suite_id)
            .outerjoin(TestType, TestType.test_type == TestResult.test_type)
            .where(TestResult.id.in_(result_ids))
        ).all()
    return [
        AuditedObject(
            id=row.id,
            project_code=row.project_code,
            name=object_name(row.test_name_short or row.test_type, row.table_name, row.column_names),
        )
        for row in rows
    ]


def _describe_issues(issue_ids: Collection[UUID]) -> list[AuditedObject]:
    if not issue_ids:
        return []
    with isolated_read() as session:
        rows = session.execute(
            select(
                HygieneIssue.id,
                HygieneIssue.project_code,
                HygieneIssue.table_name,
                HygieneIssue.column_name,
                HygieneIssueType.name,
            )
            .outerjoin(HygieneIssueType, HygieneIssueType.id == HygieneIssue.type_id)
            .where(HygieneIssue.id.in_(issue_ids))
        ).all()
    return [
        AuditedObject(
            id=row.id, project_code=row.project_code, name=object_name(row.name, row.table_name, row.column_name)
        )
        for row in rows
    ]
