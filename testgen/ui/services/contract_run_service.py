"""How the test-runs list, the results page and the Run Tests dialog describe a contract version a run measures."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from testgen.common.enums import SuiteType
from testgen.common.models.suite_version import ContractState, SuiteVersion, format_version, version_state
from testgen.common.models.test_run import TestRunSummary

PREVIEW_NOTE = "A preview does not count as the contract's status."


def run_version_caption(run: TestRunSummary) -> str | None:
    """The run's version for the test-runs list caption, e.g. ``v4 draft · Preview``, or None for an
    unversioned run."""
    label = run.version_label
    if label is None:
        return None
    return f"{label} · Preview" if run.is_preview else label


def run_version_block(run: TestRunSummary) -> dict[str, str] | None:
    """The results page's Contract Version value and its tooltip, or None for an unversioned run."""
    label = run.version_label
    if label is None:
        return None
    text = "Discarded draft" if run.version_discarded else label
    if run.version_discarded:
        tooltip = f"This run checked a draft that was later discarded. {PREVIEW_NOTE}"
    elif run.is_preview:
        tooltip = f"v{run.version_number} was not frozen when this run started. {PREVIEW_NOTE}"
    elif run.version_number == run.active_version_number:
        tooltip = f"v{run.version_number} is the agreement in force."
    else:
        tooltip = f"The contract has since moved on. v{run.active_version_number} is the agreement in force."
    classification = "Preview" if run.is_preview else "Verification"
    return {"value": f"{text} · {classification}", "tooltip": tooltip}


def run_version_line(version: SuiteVersion, active: SuiteVersion | None) -> str:
    """The Run Tests dialog's line naming the version a run checks, and whether the run counts."""
    is_active = active is not None and version.version == active.version
    label = format_version(version.version, version_state(version.frozen_at, is_active))
    if version.frozen_at is None:
        return f"Version: {label}. This run is a preview and does not count as the contract's status."
    if not is_active and active is not None:
        return f"Version: {label}. v{active.version} is the agreement in force."
    return f"Version: {label}"


def run_test_suite_options(test_suites: Iterable[Any], states: dict[UUID, ContractState]) -> list[dict[str, Any]]:
    """The Run Tests dialog's suite options, each contract's naming the version a run of it checks by default:
    the agreement in force, or the draft when none is frozen yet.

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
