"""Shared test-result disposition service.

Sets the disposition on test results and keeps the parent test definition's
active/lock state coupled: a "Muted" (``Disposition.INACTIVE``) disposition
deactivates the test definition and locks it against auto-regeneration; any
other value — or clearing the disposition — reactivates and unlocks it. Passed
test results are never dispositioned. Used by both the Streamlit UI
(test_results page) and the MCP tools. Must not import Streamlit.
"""
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update

from testgen.common.enums import Disposition
from testgen.common.models import get_current_session
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_result import TestResult, TestResultStatus


@dataclass(frozen=True)
class DispositionUpdate:
    """Outcome of a disposition write.

    ``matched`` is the number of non-Passed results updated; ``passed_skipped`` is
    the number of Passed results that matched but were left unchanged.
    """

    matched: int
    passed_skipped: int


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

    Passed results are excluded from the write. ``disposition=None`` clears it (NULL).
    Returns the matched (non-Passed, updated) and passed-skipped counts.
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

    tr_stmt = (
        update(TestResult)
        .where(*non_passed)
        .values(disposition=disposition.value if disposition is not None else None)
    )
    matched = session.execute(tr_stmt).rowcount

    test_active, lock_refresh = coupled_test_definition_state(disposition)
    td_ids_by_suite: dict[UUID, list[UUID]] = defaultdict(list)
    changing_by_suite: dict[UUID, list[UUID]] = defaultdict(list)
    for row in session.execute(
        select(
            TestResult.test_suite_id,
            TestResult.test_definition_id,
            TestDefinition.test_active,
            TestDefinition.lock_refresh,
        )
        .outerjoin(TestDefinition, TestDefinition.id == TestResult.test_definition_id)
        .where(*non_passed)
        .distinct()
    ).all():
        if row.test_definition_id is not None:
            td_ids_by_suite[row.test_suite_id].append(row.test_definition_id)
            if (row.test_active, row.lock_refresh) != (test_active, lock_refresh):
                changing_by_suite[row.test_suite_id].append(row.test_definition_id)

    # A contract's frozen version is never written: the coupling lands on the draft's copy, and a
    # definition with no writable counterpart keeps its result disposition without the coupling.
    # Where the write would open a draft, a definition already in the coupled state needs none.
    writable_td_ids: set[UUID] = set()
    for suite_id, td_ids in td_ids_by_suite.items():
        if SuiteVersion.is_frozen_agreement(session.scalar(select(SuiteVersion.resolved_for(suite_id)))):
            td_ids = changing_by_suite[suite_id]
            if not td_ids:
                continue
        writable_td_ids.update(TestDefinition.resolve_writable(suite_id, td_ids, skip_unwritable=True)[1].values())

    if writable_td_ids:
        session.execute(
            update(TestDefinition)
            .where(TestDefinition.id.in_(writable_td_ids), TestDefinition.version_clause())
            .values(
                test_active=test_active,
                lock_refresh=lock_refresh,
                last_manual_update=datetime.now(UTC).replace(tzinfo=None),
            )
        )

    return DispositionUpdate(matched=matched, passed_skipped=passed_skipped)
