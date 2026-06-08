"""Shared test-result disposition service.

Sets the disposition on test results and keeps the parent test definition's
active/lock state coupled: a "Muted" (``Disposition.INACTIVE``) disposition
deactivates the test definition and locks it against auto-regeneration; any
other value — or clearing the disposition — reactivates and unlocks it. Passed
test results are never dispositioned. Used by both the Streamlit UI
(test_results page) and the MCP tools. Must not import Streamlit.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update

from testgen.common.enums import Disposition
from testgen.common.models import get_current_session
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
    affected_td_ids = select(TestResult.test_definition_id).where(*non_passed)
    td_stmt = (
        update(TestDefinition)
        .where(TestDefinition.id.in_(affected_td_ids))
        .values(
            test_active=test_active,
            lock_refresh=lock_refresh,
            last_manual_update=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.execute(td_stmt)

    return DispositionUpdate(matched=matched, passed_skipped=passed_skipped)
