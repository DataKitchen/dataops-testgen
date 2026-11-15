from unittest.mock import MagicMock, patch

import pytest

from testgen.common.contract_rules import UndeclaredTableError, check_table_declared, writable_tables
from testgen.common.enums import SuiteType

pytestmark = pytest.mark.unit

MODULE = "testgen.common.contract_rules"
DOCUMENT = {"schema": [{"name": "orders"}, {"name": "payments"}]}


def _contract() -> MagicMock:
    return MagicMock(suite_type=SuiteType.CONTRACT, test_suite="sales")


def test_a_regular_suite_has_no_table_restriction():
    with patch(f"{MODULE}.SuiteVersion") as suite_version:
        assert writable_tables(MagicMock(suite_type=SuiteType.STANDARD)) is None
        check_table_declared(MagicMock(suite_type=SuiteType.STANDARD), "customers")
    suite_version.draft_for.assert_not_called()


def test_a_contract_reads_its_drafts_declared_tables():
    with patch(f"{MODULE}.SuiteVersion") as suite_version:
        suite_version.draft_for.return_value = MagicMock(metadata_document=DOCUMENT)
        assert writable_tables(_contract()) == ["orders", "payments"]
    suite_version.in_force_for.assert_not_called()


def test_a_contract_without_a_draft_reads_the_version_in_force():
    with patch(f"{MODULE}.SuiteVersion") as suite_version:
        suite_version.draft_for.return_value = None
        suite_version.in_force_for.return_value = MagicMock(metadata_document=DOCUMENT)
        assert writable_tables(_contract()) == ["orders", "payments"]


def test_a_contract_with_no_document_declares_no_tables():
    with patch(f"{MODULE}.SuiteVersion") as suite_version:
        suite_version.draft_for.return_value = MagicMock(metadata_document=None)
        assert writable_tables(_contract()) == []


def test_check_refuses_a_table_the_contract_does_not_declare():
    with patch(f"{MODULE}.SuiteVersion") as suite_version:
        suite_version.draft_for.return_value = MagicMock(metadata_document=DOCUMENT)
        check_table_declared(_contract(), "orders")
        with pytest.raises(UndeclaredTableError) as exc_info:
            check_table_declared(_contract(), "customers")

    assert exc_info.value.contract_name == "sales"
    assert exc_info.value.table_name == "customers"
    assert exc_info.value.declared == ["orders", "payments"]
    assert str(exc_info.value) == "Contract sales does not declare table customers."


def test_a_table_declared_by_physical_name_is_writable_by_that_name():
    document = {"schema": [{"name": "orders", "physicalName": "tbl_orders"}]}
    with patch(f"{MODULE}.SuiteVersion") as suite_version:
        suite_version.draft_for.return_value = MagicMock(metadata_document=document)
        check_table_declared(_contract(), "tbl_orders")
        with pytest.raises(UndeclaredTableError):
            check_table_declared(_contract(), "orders")
