"""Shared test-result disposition service.

Sets the disposition on test results and keeps the parent test definition's
active/lock state coupled: a "Muted" (``Disposition.INACTIVE``) disposition
deactivates the test definition and locks it against auto-regeneration; any
other value — or clearing the disposition — reactivates and unlocks it. Passed
test results are never dispositioned. A result of a managed test type is never
muted, and its test definition is never written. A contract's term keeps its lock when it is
reactivated. A contract's frozen version is never written: the change lands on its draft, which is
reported. Used by both the Streamlit UI
(test_results page) and the MCP tools. Must not import Streamlit.
"""
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update

from testgen.common.enums import MANAGED_TEST_TYPES, Disposition, SuiteType
from testgen.common.models import get_current_session
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_result import TestResult, TestResultStatus
from testgen.common.models.test_suite import TestSuite


@dataclass(frozen=True)
class ContractDraftChange:
    """Tests of a contract that a disposition muted or unmuted in its draft, not in the version in force."""

    contract_name: str
    draft_version: int
    test_count: int
    muted: bool

    def notice(self, *, counted: bool = True) -> str:
        """The change as a sentence: counted, it opens with "The test" or "The 3 tests"; otherwise with "The tests"."""
        if not counted:
            subject, plural = "The tests", True
        elif self.test_count == 1:
            subject, plural = "The test", False
        else:
            subject, plural = f"The {self.test_count} tests", True
        state = "muted" if self.muted else "unmuted"
        return (
            f"{subject} {'are' if plural else 'is'} {state} in draft v{self.draft_version} of the contract "
            f"{self.contract_name}. The active version keeps running {'them' if plural else 'it'} until the draft "
            "is frozen."
        )


@dataclass(frozen=True)
class DispositionUpdate:
    """Outcome of a disposition write.

    ``matched`` is the number of non-Passed results updated; ``passed_skipped`` is
    the number of Passed results that matched but were left unchanged; ``managed_skipped``
    is the number of non-Passed results of a managed test type left unmuted. ``contract_drafts``
    holds, for each contract whose tests changed in its draft rather than in the version in force,
    that draft and how many of its tests changed.
    """

    matched: int
    passed_skipped: int
    managed_skipped: int = 0
    contract_drafts: tuple[ContractDraftChange, ...] = ()


def coupled_test_definition_state(disposition: Disposition | None) -> tuple[bool, bool]:
    """Return the parent test definition's ``(test_active, lock_refresh)`` for a disposition.

    Muted (``INACTIVE``) → ``(False, True)``: deactivate and lock against
    auto-regeneration. Any other value, or cleared (``None``) → ``(True, False)``.
    """
    deactivate = disposition == Disposition.INACTIVE
    return (not deactivate, deactivate)


def coerce_ui_disposition(value: str | None) -> Disposition | None:
    """Map a UI disposition string to the stored value.

    The UI passes ``Confirmed`` / ``Dismissed`` / ``Inactive``, or ``No Decision`` /
    empty / ``None`` to clear. Unknown values raise ``ValueError`` (caller's bug).
    """
    if value in (None, "", "No Decision"):
        return None
    return Disposition(value)


def set_test_results_disposition(
    test_result_ids: Sequence[str | UUID],
    disposition: Disposition | None,
) -> DispositionUpdate:
    """Set ``disposition`` on the given results and couple their parent test definitions.

    Passed results are excluded from the write, and so are results of a managed test type when
    ``disposition`` mutes. The definitions of managed test types are never coupled.
    ``disposition=None`` clears it (NULL). Returns the matched (non-Passed, updated),
    passed-skipped, and managed-skipped counts.
    """
    ids = [UUID(str(rid)) for rid in test_result_ids]
    if not ids:
        return DispositionUpdate(matched=0, passed_skipped=0)

    session = get_current_session()

    passed_skipped = session.scalar(
        select(func.count())
        .select_from(TestResult)
        .where(TestResult.id.in_(ids), TestResult.status == TestResultStatus.Passed)
    ) or 0

    # NULL result_status rows (e.g. training-mode results) are excluded by `!= Passed`,
    # matching the prior UI behavior — disposition only applies to evaluated results.
    non_passed = (TestResult.id.in_(ids), TestResult.status != TestResultStatus.Passed)
    unmanaged = TestResult.test_type.not_in(MANAGED_TEST_TYPES)

    managed_skipped = 0
    writable = non_passed
    if disposition == Disposition.INACTIVE:
        managed_skipped = session.scalar(
            select(func.count())
            .select_from(TestResult)
            .where(*non_passed, TestResult.test_type.in_(MANAGED_TEST_TYPES))
        ) or 0
        writable = (*non_passed, unmanaged)

    tr_stmt = (
        update(TestResult)
        .where(*writable)
        .values(disposition=disposition.value if disposition is not None else None)
    )
    matched = session.execute(tr_stmt).rowcount

    test_active, lock_refresh = coupled_test_definition_state(disposition)
    # A contract's term is never unlocked, so generation never removes a term a user wrote; whether
    # it changes rests on test_active alone.
    contract_suites: set[UUID] = set()

    def holds(suite_id: UUID, active: bool, locked: bool) -> bool:
        return active == test_active and (suite_id in contract_suites or locked == lock_refresh)

    td_ids_by_suite: dict[UUID, list[UUID]] = defaultdict(list)
    changing_by_suite: dict[UUID, list[UUID]] = defaultdict(list)
    for row in session.execute(
        select(
            TestResult.test_suite_id,
            TestResult.test_definition_id,
            TestDefinition.test_active,
            TestDefinition.lock_refresh,
            TestSuite.suite_type,
        )
        .outerjoin(TestDefinition, TestDefinition.id == TestResult.test_definition_id)
        .join(TestSuite, TestSuite.id == TestResult.test_suite_id)
        .where(*non_passed, unmanaged)
        .distinct()
    ).all():
        if row.test_definition_id is not None:
            if row.suite_type == SuiteType.CONTRACT:
                contract_suites.add(row.test_suite_id)
            td_ids_by_suite[row.test_suite_id].append(row.test_definition_id)
            if not holds(row.test_suite_id, row.test_active, row.lock_refresh):
                changing_by_suite[row.test_suite_id].append(row.test_definition_id)

    # A contract's frozen version is never written: the coupling lands on the draft's copy, and a
    # definition with no writable counterpart keeps its result disposition without the coupling.
    # Where the write would open a draft, a definition already in the coupled state needs none, and
    # a draft copy already in the coupled state is left as it is.
    writable_td_ids: set[UUID] = set()
    lock_kept_td_ids: set[UUID] = set()
    contract_drafts: list[ContractDraftChange] = []
    for suite_id, td_ids in td_ids_by_suite.items():
        if SuiteVersion.is_frozen_agreement(session.scalar(select(SuiteVersion.resolved_for(suite_id)))):
            td_ids = changing_by_suite[suite_id]
            if not td_ids:
                continue
        version_id, mapping = TestDefinition.resolve_writable(suite_id, td_ids, skip_unwritable=True)
        targets = lock_kept_td_ids if suite_id in contract_suites and not lock_refresh else writable_td_ids
        copies = {target for source, target in mapping.items() if source != target}
        if copies:
            holding = {
                row.id
                for row in session.execute(
                    select(TestDefinition.id, TestDefinition.test_active, TestDefinition.lock_refresh).where(
                        TestDefinition.id.in_(copies), TestDefinition.version_clause()
                    )
                ).all()
                if holds(suite_id, row.test_active, row.lock_refresh)
            }
            if changed := len(copies - holding):
                contract_drafts.append(ContractDraftChange(
                    contract_name=_contract_name(suite_id),
                    draft_version=SuiteVersion.get(version_id).version,
                    test_count=changed,
                    muted=not test_active,
                ))
            targets.update(target for target in mapping.values() if target not in holding)
        else:
            targets.update(mapping.values())

    now = datetime.now(UTC).replace(tzinfo=None)
    for td_ids, lock_values in ((writable_td_ids, {"lock_refresh": lock_refresh}), (lock_kept_td_ids, {})):
        if td_ids:
            session.execute(
                update(TestDefinition)
                .where(TestDefinition.id.in_(td_ids), TestDefinition.version_clause())
                .values(test_active=test_active, last_manual_update=now, **lock_values)
            )

    return DispositionUpdate(
        matched=matched,
        passed_skipped=passed_skipped,
        managed_skipped=managed_skipped,
        contract_drafts=tuple(contract_drafts),
    )


def _contract_name(suite_id: UUID) -> str:
    return get_current_session().scalar(select(TestSuite.test_suite).where(TestSuite.id == suite_id))
