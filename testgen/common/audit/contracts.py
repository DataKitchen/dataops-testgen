import copy
from collections.abc import Collection, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select

from testgen.common.audit.actions import AuditAction, AuditTargetType
from testgen.common.audit.recorder import record
from testgen.common.audit.safety import isolated_read, never_raises
from testgen.common.audit.test_definitions import record_imported_tests
from testgen.common.contract_document import declared_tables
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_suite import TestSuite
from testgen.common.test_definition_export_import_service import ImportAction

_SUMMARIZED_FIELDS = ("schema", "version", "name")


@never_raises()
def stored_document(test_suite_id: UUID) -> dict[str, Any] | None:
    """A copy of the metadata document of the version the contract resolves to: its draft, else its active version.
    None when it can't be read. Never flushes the session."""
    with isolated_read() as session:
        document = session.scalar(
            select(SuiteVersion.metadata_document).where(SuiteVersion.id == SuiteVersion.resolved_for(test_suite_id))
        )
    return copy.deepcopy(document or {})


def document_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The top-level fields of a contract document that differ between ``before`` and ``after``, a field removed
    going to ``None``.

    The schema is listed as changed, without its values, and the tables it declares are listed under ``tables`` when
    a table was added or removed. The document's version number and name, which follow the contract's, are left out.
    """
    changes = {
        name: {"from": before.get(name), "to": after.get(name)}
        for name in dict.fromkeys([*before, *after])
        if name not in _SUMMARIZED_FIELDS and before.get(name) != after.get(name)
    }
    if before.get("schema") != after.get("schema"):
        changes["schema"] = {}
    tables_before, tables_after = declared_tables(dict(before)), declared_tables(dict(after))
    if set(tables_before) != set(tables_after):
        changes["tables"] = {"from": tables_before, "to": tables_after}
    return changes


@never_raises()
def record_document_updated(contract: TestSuite, version_id: UUID, before: Mapping[str, Any] | None) -> None:
    """Record the changes to a contract version's metadata document, against ``before``, its document as stored
    before the change. A change that left every top-level field as it was, or an unknown ``before``, records nothing.
    """
    if before is None:
        return
    version, after = _version_document(version_id)
    _record_version(AuditAction.CONTRACT_VERSION_UPDATED, contract, version, document_changes(before, after or {}))


@never_raises()
def record_document_imported(
    contract: TestSuite,
    version_id: UUID,
    before: Mapping[str, Any] | None,
    written: Mapping[ImportAction, Collection[UUID]],
) -> None:
    """Record a contract document imported into a version: the tests it created, updated, and deleted, each as one
    record, then the changes to the version's document.

    :param before: the version's document as stored before the import.
    :param written: the ids of the tests the import wrote, by what it did to them.
    """
    record_imported_tests(contract.id, contract.project_code, written)
    record_document_updated(contract, version_id, before)


@never_raises()
def record_version_frozen(contract: TestSuite, version: SuiteVersion) -> None:
    """Record a contract version frozen, with the label it was given."""
    changes = {"label": {"to": version.label}} if version.label else {}
    _record_version(AuditAction.CONTRACT_VERSION_FROZEN, contract, version.version, changes)


@never_raises()
def record_draft_discarded(contract: TestSuite, version: int) -> None:
    """Record a contract's draft, version ``version``, discarded."""
    _record_version(AuditAction.CONTRACT_VERSION_DELETED, contract, version)


def _version_document(version_id: UUID) -> tuple[int, dict[str, Any] | None]:
    with isolated_read() as session:
        return session.execute(
            select(SuiteVersion.version, SuiteVersion.metadata_document).where(SuiteVersion.id == version_id)
        ).one()


def _record_version(
    action: AuditAction, contract: TestSuite, version: int, changes: dict[str, dict[str, Any]] | None = None
) -> None:
    record(
        action,
        project_code=contract.project_code,
        target_type=AuditTargetType.CONTRACT_VERSION,
        targets=[contract.id],
        target_name=f"{contract.test_suite} v{version}",
        changes=changes or {},
    )
