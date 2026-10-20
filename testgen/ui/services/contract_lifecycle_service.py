"""What the Freeze Version dialog asks and reports for a contract's draft."""

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
        "consequence": f"Version {draft.version} becomes the agreement in force{replacing}. {FREEZE_CONSEQUENCE}",
    }


def freeze(suite: TestSuite, label: str | None) -> dict[str, Any]:
    """Freeze the contract's draft.

    :param label: the name to give the version; blank for none
    :return: ``success``, the ``message`` to show, and the validator's ``problems`` when the
        contract document does not validate
    """
    draft = SuiteVersion.draft_for(suite.id)
    if draft is None:
        return {"success": False, "message": "This contract has no draft to freeze.", "problems": []}
    try:
        frozen = contract_service.freeze_version(suite, label=(label or "").strip() or None)
    except InvalidContractDocumentError as e:
        return {
            "success": False,
            "message": f"Version {draft.version} cannot be frozen. The contract document is not valid ODCS:",
            "problems": e.problems,
        }
    except ValueError as e:
        return {"success": False, "message": str(e), "problems": []}
    return {"success": True, "message": f"Version {frozen.version} of {suite.test_suite} frozen.", "problems": []}
