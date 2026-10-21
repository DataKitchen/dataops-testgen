from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.contract_service import ContractStatus
from testgen.common.models.suite_version import SuiteVersion, SuiteVersionListItem
from testgen.common.models.test_suite import TestSuite
from testgen.ui.services import contract_page_service as service

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 8, 1, tzinfo=UTC)
SUITE_ID = uuid4()


def _item(version: int, frozen: bool) -> SuiteVersionListItem:
    return SuiteVersionListItem(
        id=uuid4(), version=version, label=None, created_by=None, frozen_at=FROZEN if frozen else None,
        frozen_by=None, term_count=0, run_count=0, latest_run_id=None, latest_run_status=None,
        latest_run_started_at=None,
    )


def _page(items: list[SuiteVersionListItem], version_param: str | None, can_edit: bool = True, terms: int = 5):
    suite = TestSuite(id=SUITE_ID, test_suite="orders_contract", suite_type="contract")
    status = ContractStatus(active=None, draft=None, latest_verification=None, incomplete_run=None, unavailable=None)
    with (
        patch.object(service.SuiteVersion, "list_for_suite", return_value=(items, len(items))),
        patch.object(service.contract_service, "contract_status", return_value=status),
        patch.object(service.contract_service, "term_count", return_value=terms) as term_count,
    ):
        page = service.contract_page(suite, version_param, can_edit)
    return page, term_count


def test_the_page_opens_on_the_draft_and_reads_the_resolved_version():
    draft, active = _item(4, False), _item(3, True)

    page, term_count = _page([draft, active], None)

    assert page.summary["selected_version"] == 4
    assert page.selected_version_id == draft.id
    assert page.read_version_id is None
    assert page.editable is True
    term_count.assert_called_once_with(draft.id)


def test_without_a_draft_the_active_version_is_editable():
    active, superseded = _item(3, True), _item(2, True)

    page, _ = _page([active, superseded], None)

    assert page.summary["selected_version"] == 3
    assert page.read_version_id is None
    assert page.editable is True


@pytest.mark.parametrize("version_param", ["3", "2"])
def test_another_version_is_read_by_its_id_and_cannot_be_edited(version_param):
    draft, active, superseded = _item(4, False), _item(3, True), _item(2, True)

    page, _ = _page([draft, active, superseded], version_param)

    selected = active if version_param == "3" else superseded
    assert page.read_version_id == selected.id
    assert page.selected_version_id == selected.id
    assert page.editable is False


@pytest.mark.parametrize("version_param", ["9", "v3", ""])
def test_an_unknown_version_falls_back_to_the_editable_one(version_param):
    draft, active = _item(4, False), _item(3, True)

    page, _ = _page([draft, active], version_param)

    assert page.summary["selected_version"] == 4
    assert page.read_version_id is None


def test_a_user_without_edit_permission_cannot_edit_the_editable_version():
    page, _ = _page([_item(4, False), _item(3, True)], None, can_edit=False)

    assert page.editable is False
    assert page.read_version_id is None


def test_the_run_tests_dialog_names_the_selected_version_and_runs_it():
    draft, active, superseded = _item(4, False), _item(3, True), _item(2, True)

    page, _ = _page([draft, active, superseded], "2")

    assert page.run_option == {
        "value": str(SUITE_ID),
        "label": "orders_contract",
        "suite_type": "contract",
        "version_line": "Version: v2 superseded. v3 is the agreement in force.",
        "version_id": str(superseded.id),
    }


def test_a_draft_run_says_it_is_a_preview():
    page, _ = _page([_item(1, False)], None)

    assert page.run_option["version_line"] == (
        "Version: v1 draft. This run is a preview and does not count as the contract's status."
    )


def test_a_version_without_terms_cannot_be_run():
    page, _ = _page([_item(4, False), _item(3, True)], None, terms=0)

    assert page.run_disabled_reason == "This contract has no quality terms to run."


def test_a_version_with_terms_can_be_run():
    page, _ = _page([_item(4, False), _item(3, True)], None)

    assert page.run_disabled_reason is None


def test_the_editable_version_number_is_the_draft_else_the_active_version():
    with (
        patch.object(service.SuiteVersion, "draft_for", return_value=None),
        patch.object(service.SuiteVersion, "in_force_for", return_value=SuiteVersion(version=3, frozen_at=FROZEN)),
    ):
        assert service.editable_version_number(TestSuite(id=uuid4())) == 3
    with patch.object(service.SuiteVersion, "draft_for", return_value=SuiteVersion(version=4)):
        assert service.editable_version_number(TestSuite(id=uuid4())) == 4
