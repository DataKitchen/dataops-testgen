from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import SuiteType
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.ui.services.test_definition_service import (
    MANAGED_ADD_MESSAGE,
    MANAGED_EDIT_MESSAGE,
    dialog_catalog,
    dialog_table_columns,
    save_from_dialog,
)

pytestmark = pytest.mark.unit

SERVICE_MODULE = "testgen.ui.services.test_definition_service"

DIVERGENCE = TestType(
    test_type="Divergence",
    test_name_short="Divergence",
    test_scope="column",
    default_parm_columns="threshold_value",
    default_parm_prompts="Maximum Divergence Level",
    default_parm_required="Y",
)
ROW_COUNT = TestType(test_type="Row_Count", test_name_short="Row Count", test_scope="table")
REGULAR_SUITE = MagicMock(suite_type=SuiteType.REGULAR)
CONTRACT = MagicMock(suite_type=SuiteType.CONTRACT)


def _save(
    definition: TestDefinition,
    test_type: TestType,
    suite: MagicMock = REGULAR_SUITE,
    declared: list[str] | None = None,
    stored_table: str | None = None,
    stored_type: str | None = None,
) -> tuple[str | None, bool]:
    with (
        patch(f"{SERVICE_MODULE}.TestType.get", return_value=test_type),
        patch(f"{SERVICE_MODULE}.writable_tables", return_value=declared),
        patch(f"{SERVICE_MODULE}._stored_table_name", return_value=stored_table),
        patch(f"{SERVICE_MODULE}._stored_test_type", return_value=stored_type or test_type.test_type),
        patch.object(TestDefinition, "save") as save,
    ):
        error = save_from_dialog(definition, suite)
    return error, save.called


def test_valid_definition_is_saved():
    definition = TestDefinition(test_type="Divergence", table_name="t1", column_name="c1", threshold_value="0.1")

    assert _save(definition, DIVERGENCE) == (None, True)


def test_invalid_definition_is_not_saved_and_names_fields_by_their_prompts():
    definition = TestDefinition(test_type="Divergence", table_name="t1", column_name="c1", severity="Bogus")

    error, saved = _save(definition, DIVERGENCE)

    assert not saved
    assert error == (
        "The test could not be saved. Severity: must be one of Fail, Warning, Log (got Bogus); "
        "Maximum Divergence Level: required for test type Divergence."
    )


def test_fields_the_dialog_cannot_show_are_cleared_rather_than_rejected():
    """The dialog sends back the stored row, including fields it hides from the user."""
    definition = TestDefinition(test_type="Row_Count", table_name="t1", column_name="c1", custom_query="SELECT 1")

    assert _save(definition, ROW_COUNT) == (None, True)
    assert definition.column_name is None
    assert definition.custom_query is None


def test_non_public_type_is_saved_without_validation():
    definition = TestDefinition(test_type="Volume_Trend", custom_query="SELECT COUNT(*)")

    with patch(f"{SERVICE_MODULE}.TestType.get") as get_test_type, patch.object(TestDefinition, "save") as save:
        assert save_from_dialog(definition, REGULAR_SUITE) is None

    get_test_type.assert_not_called()
    save.assert_called_once()
    assert definition.custom_query == "SELECT COUNT(*)"


SCHEMA_CONFORMANCE = TestType(test_type="Schema_Conformance", test_name_short="Schema Conformance", test_scope="table")


def test_new_test_of_a_managed_type_is_refused():
    definition = TestDefinition(test_type="Schema_Conformance", table_name="t1")

    assert _save(definition, SCHEMA_CONFORMANCE) == (MANAGED_ADD_MESSAGE, False)


def test_edit_of_a_managed_test_is_refused():
    definition = TestDefinition(id=uuid4(), test_type="Schema_Conformance", table_name="t1")

    assert _save(definition, SCHEMA_CONFORMANCE) == (MANAGED_EDIT_MESSAGE, False)


def test_edit_changing_a_managed_test_to_another_type_is_refused():
    definition = TestDefinition(id=uuid4(), test_type="Row_Count", table_name="t1")

    assert _save(definition, ROW_COUNT, stored_type="Schema_Conformance") == (MANAGED_EDIT_MESSAGE, False)


UNDECLARED_MESSAGE = (
    "The contract does not declare the table customers. Add it under Schema on the Contract Metadata tab, or choose "
    "a declared table."
)


def test_new_test_on_a_table_the_contract_does_not_declare_is_refused():
    definition = TestDefinition(test_type="Row_Count", table_name="customers")

    assert _save(definition, ROW_COUNT, CONTRACT, declared=["orders"]) == (UNDECLARED_MESSAGE, False)


@pytest.mark.parametrize("table_name", [None, ""])
def test_new_test_naming_no_table_on_a_contract_is_refused(table_name):
    definition = TestDefinition(test_type="CUSTOM", table_name=table_name)

    assert _save(definition, ROW_COUNT, CONTRACT, declared=["orders"]) == (
        "A test on a contract must name one of the tables the contract declares.",
        False,
    )


def test_new_test_on_a_declared_table_is_saved():
    definition = TestDefinition(test_type="Row_Count", table_name="orders")

    assert _save(definition, ROW_COUNT, CONTRACT, declared=["orders"]) == (None, True)


def test_edit_moving_a_test_to_an_undeclared_table_is_refused():
    definition = TestDefinition(id=uuid4(), test_type="Row_Count", table_name="customers")

    assert _save(definition, ROW_COUNT, CONTRACT, declared=["orders"], stored_table="orders") == (
        UNDECLARED_MESSAGE,
        False,
    )


def test_edit_keeping_an_undeclared_table_is_saved():
    definition = TestDefinition(id=uuid4(), test_type="Row_Count", table_name="customers")

    assert _save(definition, ROW_COUNT, CONTRACT, declared=["orders"], stored_table="customers") == (None, True)


def test_regular_suite_saves_a_test_on_any_table():
    definition = TestDefinition(test_type="Row_Count", table_name="customers")

    assert _save(definition, ROW_COUNT, REGULAR_SUITE, declared=None) == (None, True)


TABLE_COLUMNS = [
    {"table_name": "orders", "column_name": "id"},
    {"table_name": "customers", "column_name": "id"},
    {"table_name": "payments", "column_name": "id"},
]


def test_dialog_offers_every_table_on_a_regular_suite():
    with patch(f"{SERVICE_MODULE}.writable_tables", return_value=None):
        assert dialog_table_columns(REGULAR_SUITE, TABLE_COLUMNS) == TABLE_COLUMNS


def test_dialog_offers_the_declared_tables_and_the_edited_tests_table_on_a_contract():
    with patch(f"{SERVICE_MODULE}.writable_tables", return_value=["orders"]):
        assert [c["table_name"] for c in dialog_table_columns(CONTRACT, TABLE_COLUMNS)] == ["orders"]
        assert [c["table_name"] for c in dialog_table_columns(CONTRACT, TABLE_COLUMNS, "payments")] == [
            "orders",
            "payments",
        ]



def test_dialog_catalog_lists_every_catalog_table_beside_the_offered_columns():
    with patch(f"{SERVICE_MODULE}.writable_tables", return_value=["orders"]):
        catalog = dialog_catalog(CONTRACT, TABLE_COLUMNS)

    assert [c["table_name"] for c in catalog["table_columns"]] == ["orders"]
    assert catalog["catalog_tables"] == ["customers", "orders", "payments"]

LOV_ALL = TestType(
    test_type="LOV_All",
    test_name_short="Value Match All",
    test_scope="column",
    default_parm_columns="baseline_value,threshold_value",
    default_parm_prompts="List of Expected Values,Threshold Mismatch Count",
    default_parm_required="Y,N",
)


def _save_on_catalog_column(definition: TestDefinition, general_type: str) -> tuple[str | None, bool]:
    with patch.object(DataColumnChars, "select_general_types", return_value={("t1", "c1"): general_type}):
        return _save(definition, LOV_ALL)


@pytest.mark.parametrize(
    ("general_type", "entered", "stored"),
    [
        ("N", "1.5, 2,1.50", "1.5,2"),
        ("A", "a,A,a,a b", "a,A,a b"),
    ],
)
def test_value_list_is_saved_without_duplicates(general_type, entered, stored):
    definition = TestDefinition(
        test_type="LOV_All", table_groups_id=uuid4(), table_name="t1", column_name="c1", baseline_value=entered
    )

    assert _save_on_catalog_column(definition, general_type) == (None, True)
    assert definition.baseline_value == stored


def test_value_list_for_a_numeric_column_is_refused_when_it_holds_a_non_number():
    definition = TestDefinition(
        test_type="LOV_All", table_groups_id=uuid4(), table_name="t1", column_name="c1", baseline_value="1,x"
    )

    assert _save_on_catalog_column(definition, "N") == (
        "The test could not be saved. List of Expected Values: contains a value that is not a number: x.",
        False,
    )
