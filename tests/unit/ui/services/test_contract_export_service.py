from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.contract_service import ExportedDocument
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_suite import TestSuite
from testgen.ui.services.contract_export_service import contract_export

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.services.contract_export_service"
DOCUMENT = "apiVersion: v3.2.0\nkind: DataContract\nname: orders_contract\n"


def _suite() -> TestSuite:
    return TestSuite(id=uuid4(), test_suite="orders_contract")


def _export(version: SuiteVersion, exported: ExportedDocument | Exception, is_active: bool = False, requested=None):
    suite = _suite()
    with (
        patch(f"{MODULE}.contract_service.version_for_export", return_value=version) as for_export,
        patch(f"{MODULE}.contract_service.export_file", side_effect=[exported]) as export_file,
        patch(f"{MODULE}.SuiteVersion.is_active", return_value=is_active),
    ):
        result = contract_export(suite, requested)
    for_export.assert_called_once_with(suite, requested)
    export_file.assert_called_once_with(version, contract_name="orders_contract")
    return result


def test_a_draft_exports_its_rendered_document():
    draft = SuiteVersion(id=uuid4(), version=4, frozen_at=None)
    assert _export(draft, ExportedDocument(DOCUMENT, []), requested=4) == {
        "contract": "orders_contract",
        "version": "v4 draft",
        "document": DOCUMENT,
        "file_name": "orders_contract_v4_draft.yaml",
        "problems": [],
        "error": None,
    }


def test_the_active_version_is_named_active():
    active = SuiteVersion(id=uuid4(), version=3, frozen_at=datetime(2026, 8, 1, tzinfo=UTC))
    result = _export(active, ExportedDocument(DOCUMENT, []), is_active=True)
    assert result["version"] == "v3 active"
    assert result["file_name"] == "orders_contract_v3_active.yaml"


def test_a_superseded_version_is_named_superseded():
    superseded = SuiteVersion(id=uuid4(), version=2, frozen_at=datetime(2026, 7, 1, tzinfo=UTC))
    result = _export(superseded, ExportedDocument(DOCUMENT, []), is_active=False)
    assert result["version"] == "v2 superseded"
    assert result["file_name"] == "orders_contract_v2_superseded.yaml"


def test_a_document_that_does_not_validate_still_exports_with_its_problems():
    draft = SuiteVersion(id=uuid4(), version=4, frozen_at=None)
    problems = ["servers[0].schema is required"]
    result = _export(draft, ExportedDocument(DOCUMENT, problems))
    assert result["document"] == DOCUMENT
    assert result["problems"] == problems
    assert result["error"] is None


def test_a_document_that_cannot_be_rendered_reports_why():
    draft = SuiteVersion(id=uuid4(), version=4, frozen_at=None)
    result = _export(draft, ValueError("Term 12 names a column the contract does not declare."))
    assert result["document"] is None
    assert result["file_name"] is None
    assert result["error"] == "Term 12 names a column the contract does not declare."
    assert result["version"] == "v4 draft"


def test_a_file_name_keeps_only_safe_characters():
    suite = TestSuite(id=uuid4(), test_suite="sales / orders: EU")
    draft = SuiteVersion(id=uuid4(), version=1, frozen_at=None)
    with (
        patch(f"{MODULE}.contract_service.version_for_export", return_value=draft),
        patch(f"{MODULE}.contract_service.export_file", return_value=ExportedDocument(DOCUMENT, [])),
        patch(f"{MODULE}.SuiteVersion.is_active", return_value=False),
    ):
        assert contract_export(suite, None)["file_name"] == "sales_orders_EU_v1_draft.yaml"
