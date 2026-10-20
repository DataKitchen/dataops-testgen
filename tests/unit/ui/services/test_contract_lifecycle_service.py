from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.contract_service import InvalidContractDocumentError
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_suite import TestSuite
from testgen.ui.services import contract_lifecycle_service as service

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 8, 1, tzinfo=UTC)


def _suite() -> TestSuite:
    return TestSuite(id=uuid4(), test_suite="orders_contract")


def _versions(draft: int | None, active: int | None):
    return (
        patch.object(
            service.SuiteVersion, "draft_for",
            return_value=SuiteVersion(id=uuid4(), version=draft, frozen_at=None) if draft else None,
        ),
        patch.object(
            service.SuiteVersion, "in_force_for",
            return_value=SuiteVersion(id=uuid4(), version=active, frozen_at=FROZEN) if active else None,
        ),
    )


def test_freezing_a_draft_beside_the_active_version_says_what_it_replaces():
    draft, active = _versions(4, 3)
    with draft, active:
        assert service.freeze_dialog(_suite()) == {
            "title": "Freeze Version 4",
            "question": "Freeze version 4 of the contract orders_contract?",
            "consequence": "Version 4 becomes the agreement in force, replacing version 3. "
            "Its terms and its document cannot change after freezing.",
        }


def test_freezing_the_first_draft_replaces_nothing():
    draft, active = _versions(1, None)
    with draft, active:
        assert service.freeze_dialog(_suite())["consequence"] == (
            "Version 1 becomes the agreement in force. Its terms and its document cannot change after freezing."
        )


def test_a_contract_without_a_draft_has_nothing_to_freeze():
    draft, active = _versions(None, 3)
    with draft, active:
        assert service.freeze_dialog(_suite()) is None


def _freeze(label, side_effect=None, draft_version=4):
    suite = _suite()
    frozen = SuiteVersion(id=uuid4(), version=draft_version, frozen_at=FROZEN)
    draft, active = _versions(draft_version, 3)
    with (
        draft,
        active,
        patch.object(service.contract_service, "freeze_version", return_value=frozen, side_effect=side_effect) as freeze,
    ):
        result = service.freeze(suite, label)
    return result, freeze, suite


def test_freezing_reports_the_version_frozen():
    result, freeze, suite = _freeze("Q4 agreement")

    assert result == {"success": True, "message": "Version 4 of orders_contract frozen.", "problems": []}
    freeze.assert_called_once_with(suite, label="Q4 agreement")


@pytest.mark.parametrize("label", [None, "", "   "])
def test_a_blank_label_is_no_label(label):
    _, freeze, suite = _freeze(label)

    freeze.assert_called_once_with(suite, label=None)


def test_a_label_is_trimmed():
    _, freeze, suite = _freeze("  Q4 agreement ")

    freeze.assert_called_once_with(suite, label="Q4 agreement")


def test_a_document_that_does_not_validate_is_refused_with_its_problems():
    problems = ["servers[0].schema is required", "schema[2].properties[4].logicalType must be one of …"]
    result, *_ = _freeze(None, side_effect=InvalidContractDocumentError(problems))

    assert result == {
        "success": False,
        "message": "Version 4 cannot be frozen. The contract document is not valid ODCS:",
        "problems": problems,
    }


def test_any_other_refusal_is_reported():
    result, *_ = _freeze(None, side_effect=ValueError("Term 12 names a column the contract does not declare."))

    assert result == {
        "success": False, "message": "Term 12 names a column the contract does not declare.", "problems": [],
    }


def test_a_contract_without_a_draft_is_refused_without_freezing():
    draft, active = _versions(None, 3)
    with draft, active, patch.object(service.contract_service, "freeze_version") as freeze:
        result = service.freeze(_suite(), None)

    assert result == {"success": False, "message": "This contract has no draft to freeze.", "problems": []}
    freeze.assert_not_called()
