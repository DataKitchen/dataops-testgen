"""How the test-runs list, the results page and the Run Tests dialog describe a contract version a run measures."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import func, literal, select
from sqlalchemy.dialects import postgresql

from testgen.common.enums import SuiteType
from testgen.common.models import get_current_session
from testgen.common.models.suite_version import (
    ContractState,
    SuiteVersion,
    SuiteVersionListItem,
    format_version,
    version_state,
)
from testgen.common.models.test_run import TestRunSummary

VERIFICATION_NOTE = "Only a verification updates the contract's results."


def run_list_args(test_suite_id: UUID | str, version_id: UUID | str | None) -> dict[str, str]:
    """The Test Runs URL args that list a run of the suite started now: every version when the default list,
    which shows only runs of the version in force, would hide it.

    :param version_id: the version the run was started for; None for the one a run of the suite checks by default
    """
    uuid_type = postgresql.UUID(as_uuid=True)
    checked_version = func.coalesce(
        literal(version_id, uuid_type), SuiteVersion.for_run(literal(test_suite_id, uuid_type))
    )
    in_force = get_current_session().scalar(select(SuiteVersion.in_force_at(checked_version, func.now())))
    return {} if in_force else {"all_versions": "true"}


def run_version_caption(run: TestRunSummary) -> str | None:
    """The run's version for the test-runs list caption, e.g. ``v3 active``, ``v4 draft · Preview`` or
    ``v2 superseded · Out of force``, or None for an unversioned run."""
    label = run.version_label
    if label is None:
        return None
    if run.is_preview:
        return f"{label} · Preview"
    if run.is_out_of_force:
        return f"{label} · Out of force"
    return label


def run_version_block(run: TestRunSummary) -> dict[str, str] | None:
    """The results page's Contract Version value and its tooltip, or None for an unversioned run."""
    label = run.version_label
    if label is None:
        return None
    text = "Discarded draft" if run.version_discarded else label
    if run.version_discarded:
        tooltip = f"This run checked a draft that was later discarded. {VERIFICATION_NOTE}"
    elif run.is_preview:
        tooltip = f"v{run.version_number} was not frozen when this run started. {VERIFICATION_NOTE}"
    elif run.is_out_of_force:
        tooltip = f"v{run.version_number} was already superseded when this run started. {VERIFICATION_NOTE}"
    elif run.version_number == run.active_version_number:
        tooltip = f"v{run.version_number} is the active version."
    else:
        tooltip = f"v{run.active_version_number} is the active version."
    classification = "Preview" if run.is_preview else "Out of force" if run.is_out_of_force else "Verification"
    return {"value": f"{text} · {classification}", "tooltip": tooltip}


def run_version_line(
    version: SuiteVersion | SuiteVersionListItem, active: SuiteVersion | SuiteVersionListItem | None
) -> str:
    """The Run Tests dialog's line naming the version a run checks, and whether the run counts."""
    is_active = active is not None and version.version == active.version
    label = format_version(version.version, version_state(version.frozen_at, is_active))
    if version.frozen_at is None:
        return f"Version: {label}. This run is a preview. Only a verification updates the contract's results."
    if not is_active and active is not None:
        return f"Version: {label}. v{active.version} is the active version."
    return f"Version: {label}"


def run_test_suite_options(test_suites: Iterable[Any], states: dict[UUID, ContractState]) -> list[dict[str, Any]]:
    """The Run Tests dialog's suite options, each contract's naming the version a run of it checks by default:
    the active version, or the draft when none is frozen yet.

    :param test_suites: suites with ``id``, ``test_suite`` and ``suite_type``
    :param states: each contract's versions, as ``SuiteVersion.states_for`` returns them
    """
    options = []
    for suite in test_suites:
        state = states.get(suite.id) if suite.suite_type == SuiteType.CONTRACT else None
        version_line = None
        if state and (default := state.active or state.draft):
            version_line = run_version_line(default, state.active)
        options.append({
            "value": str(suite.id),
            "label": suite.test_suite,
            "suite_type": suite.suite_type,
            "version_line": version_line,
        })
    return options
