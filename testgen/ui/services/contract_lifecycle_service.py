"""What the Freeze Version and Discard Draft dialogs ask and report for a contract's draft."""

from typing import Any

from testgen.common import contract_service
from testgen.common.contract_service import InvalidContractDocumentError
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_suite import TestSuite

FREEZE_CONSEQUENCE = "Its terms and its document cannot change after freezing."


def freeze_dialog(suite: TestSuite) -> dict[str, str] | None:
    """The Freeze Version dialog's title and text for the contract's draft, or None when it has no draft."""
    draft = SuiteVersion.draft_for(suite.id)
    if draft is None:
        return None
    active = SuiteVersion.in_force_for(suite.id)
    replacing = f", replacing version {active.version}" if active else ""
    return {
        "title": f"Freeze Version {draft.version}",
        "question": f"Freeze version {draft.version} of the contract {suite.test_suite}?",
        "consequence": f"Version {draft.version} becomes the active version{replacing}. {FREEZE_CONSEQUENCE}",
    }


def freeze(suite: TestSuite, label: str | None, username: str | None) -> dict[str, Any]:
    """Freeze the contract's draft.

    :param label: the name to give the version; blank for none
    :param username: who freezes it
    :return: ``success``, the ``message`` to show, and the validator's ``problems`` when the
        contract document does not validate
    """
    draft = SuiteVersion.draft_for(suite.id)
    if draft is None:
        return {"success": False, "message": "This contract has no draft to freeze.", "problems": []}
    try:
        frozen = contract_service.freeze_version(suite, label=label, username=username)
    except InvalidContractDocumentError as e:
        return {
            "success": False,
            "message": f"Version {draft.version} cannot be frozen. The contract document is not valid ODCS:",
            "problems": e.problems,
        }
    except ValueError as e:
        return {"success": False, "message": str(e), "problems": []}
    return {"success": True, "message": f"Version {frozen.version} of {suite.test_suite} frozen.", "problems": []}


def discard_dialog(suite: TestSuite) -> dict[str, Any] | None:
    """The Discard Draft dialog's text for the contract's draft, or None when the contract has no draft
    or no frozen version to return to."""
    draft = SuiteVersion.draft_for(suite.id)
    active = SuiteVersion.in_force_for(suite.id)
    if draft is None or active is None:
        return None
    terms = contract_service.term_count(draft.id)
    term_text = f"{terms} {'term' if terms == 1 else 'terms'}"
    deleted = f"The draft's {term_text} and its document" if terms else "The draft's document"
    return {
        "question": f"Are you sure you want to discard the draft v{draft.version} of the contract {suite.test_suite}?",
        "warning": f"{deleted} will be permanently deleted. "
        f"The contract returns to version {active.version}, the active version.",
        "confirmation": f"Yes, discard the draft v{draft.version}" + (f" and its {term_text}." if terms else "."),
        "compare": {
            "label": f"Compare v{draft.version} with v{active.version}",
            "source": active.version,
            "target": draft.version,
        },
    }


def discard(suite: TestSuite) -> dict[str, Any]:
    """Discard the contract's draft and its terms.

    :return: ``success`` and the ``message`` to show
    """
    draft = SuiteVersion.draft_for(suite.id)
    if draft is None:
        return {"success": False, "message": "This contract has no draft to discard."}
    try:
        contract_service.discard_draft(suite)
    except ValueError as e:
        return {"success": False, "message": str(e)}
    return {"success": True, "message": f"Draft v{draft.version} of {suite.test_suite} discarded."}
