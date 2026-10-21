"""Which version of a contract its test-definitions page shows, and what the page may do with it."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from testgen.common import contract_service
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_suite import TestSuite
from testgen.ui.services.contract_run_service import run_version_line
from testgen.ui.services.contract_summary_service import contract_summary

NO_TERMS_TO_RUN = "This contract has no quality terms to run."

_VERSION_LIMIT = 1000


@dataclass(frozen=True)
class ContractPage:
    """The version on screen and what the page offers for it.

    ``read_version_id`` is set when the version on screen is not the one the suite resolves to, so reads
    name it; writes always land on the resolved version, and the page offers none on any other.
    """

    summary: dict[str, Any]
    selected_version_id: UUID
    read_version_id: UUID | None
    editable: bool
    run_option: dict[str, Any]
    run_disabled_reason: str | None


def contract_page(suite: TestSuite, version_param: str | None, can_edit: bool) -> ContractPage:
    """The contract's page for the version the URL names, or for its editable version when it names none
    the contract has.

    :param version_param: the ``version`` query parameter, a version number
    :param can_edit: whether the user may write to the contract
    """
    items, _ = SuiteVersion.list_for_suite(suite.id, page=1, limit=_VERSION_LIMIT)
    status = contract_service.contract_status(suite)
    requested = int(version_param) if version_param and version_param.isdigit() else None
    summary = contract_summary(items, requested, can_edit, status.latest_verification, status.incomplete_run)

    selected = next(item for item in items if item.version == summary["selected_version"])
    active = next((item for item in items if item.frozen_at is not None), None)
    editable = next((item for item in items if item.frozen_at is None), active)
    is_editable_version = selected is editable

    return ContractPage(
        summary=summary,
        selected_version_id=selected.id,
        read_version_id=None if is_editable_version else selected.id,
        editable=can_edit and is_editable_version,
        run_option={
            "value": str(suite.id),
            "label": suite.test_suite,
            "suite_type": suite.suite_type,
            "version_line": run_version_line(selected, active),
            "version_id": str(selected.id),
        },
        run_disabled_reason=None if contract_service.term_count(selected.id) else NO_TERMS_TO_RUN,
    )


def editable_version_number(suite: TestSuite) -> int | None:
    """The number of the contract's editable version: its draft, else its active version."""
    version = SuiteVersion.draft_for(suite.id) or SuiteVersion.in_force_for(suite.id)
    return version.version if version else None
