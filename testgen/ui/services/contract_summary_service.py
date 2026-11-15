"""What the contract summary row on the test-definitions page shows for the selected version."""

from collections.abc import Sequence
from typing import Any

from testgen.common.models.suite_version import (
    SuiteVersion,
    SuiteVersionListItem,
    VersionState,
    format_version,
    version_state,
)
from testgen.common.models.test_run import TestRunSummary

NOT_FROZEN_YET = "Not frozen yet. Runs of the draft are previews."


def contract_summary(
    versions: Sequence[SuiteVersion | SuiteVersionListItem],
    selected_version: int | None,
    can_edit: bool,
    verification: TestRunSummary | None,
    incomplete_run: TestRunSummary | None = None,
) -> dict[str, Any]:
    """The summary row's props for a contract.

    :param versions: every version of the contract, in any order
    :param selected_version: the version number on screen; the editable version when None or unknown
    :param can_edit: whether the user may write to the contract
    :param verification: the latest completed verification of the active version, if any
    :param incomplete_run: the active version's latest run since it was frozen, when that run has not completed
    :return: the version options, the state text, the selected version's caption and the actions it offers
    """
    ordered = sorted(versions, key=lambda version: version.version, reverse=True)
    draft = next((version for version in ordered if version.frozen_at is None), None)
    active = next((version for version in ordered if version.frozen_at is not None), None)
    editable = draft or active
    if editable is None:
        raise ValueError("A contract has at least one version.")
    selected = next((version for version in ordered if version.version == selected_version), editable)

    def label(version: SuiteVersion | SuiteVersionListItem) -> str:
        return format_version(version.version, version_state(version.frozen_at, version is active))

    caption = None
    caption_link = None
    if selected is not editable:
        if selected is active:
            caption = f"Viewing v{selected.version}, the active version."
        else:
            caption = f"Viewing v{selected.version}, a superseded version."
        if draft:
            caption = f"{caption} Edits go to the draft." if can_edit else caption
        else:
            caption = f"{caption} v{editable.version} is the active version."
        caption_link = {"label": f"Go to {label(editable)}", "version": editable.version}
    elif selected is active and can_edit:
        caption = f"Editing creates draft v{selected.version + 1}."

    is_editable = selected is editable and can_edit
    is_draft = is_editable and selected is draft

    verification_props = None
    verification_message = None
    if not active:
        verification_message = NOT_FROZEN_YET
    elif verification is None and incomplete_run is not None:
        verification_message = (
            f"v{active.version} has no completed run since it was frozen. Latest run: {incomplete_run.status_label}."
        )
    elif verification is None:
        verification_message = f"v{active.version} has not run since it was frozen."
    else:
        verification_props = {
            "version": f"v{active.version}",
            "run_id": str(verification.job_execution_id),
            "started_at": int(verification.started_at.timestamp() * 1000) if verification.started_at else None,
            "passed_ct": verification.passed_ct,
            "warning_ct": verification.warning_ct,
            "failed_ct": verification.failed_ct,
            "error_ct": verification.error_ct,
            "log_ct": verification.log_ct,
            "dismissed_ct": verification.dismissed_ct,
        }

    return {
        "versions": [{"value": version.version, "label": label(version)} for version in ordered],
        "selected_version": selected.version,
        "state": " · ".join(
            format_version(version.version, state)
            for version, state in ((active, VersionState.ACTIVE), (draft, VersionState.DRAFT))
            if version
        ),
        "caption": caption,
        "caption_link": caption_link,
        "verification": verification_props,
        "verification_message": verification_message,
        "draft_version": selected.version if is_draft else None,
        "actions": {
            "history": True,
            "export": True,
            "import": is_editable,
            "discard": is_draft and active is not None,
            "freeze": is_draft,
        },
    }
