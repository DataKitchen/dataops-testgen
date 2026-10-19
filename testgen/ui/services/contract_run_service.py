"""How the test-runs list and the results page describe the contract version a run measured."""

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
