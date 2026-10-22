from sqlalchemy import select

from testgen.common.contract_rules import writable_tables
from testgen.common.enums import MANAGED_TEST_TYPES
from testgen.common.models import get_current_session
from testgen.common.models.test_definition import (
    COLUMN_NAME_SCOPES,
    NON_PUBLIC_TEST_TYPES,
    InvalidTestDefinitionFields,
    TestDefinition,
    TestType,
)
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal

MANAGED_ADD_MESSAGE = "TestGen creates tests of this type itself. They cannot be added by hand."
MANAGED_EDIT_MESSAGE = "TestGen manages this test. It cannot be edited."


def save_from_dialog(definition: TestDefinition, suite: TestSuite | TestSuiteMinimal) -> str | None:
    """Validate and save a test definition built from the Add Test or Edit Test dialog.

    On a contract, a new test and an edit that changes the test's table must target a table the contract
    declares. An edit that keeps the table is not checked.

    A test of a managed test type is never saved: TestGen creates and updates those itself.

    Returns a message naming each invalid field, the undeclared table, or the managed test, without saving,
    when the save is refused; None once saved.
    """
    if definition.test_type in MANAGED_TEST_TYPES:
        return MANAGED_ADD_MESSAGE if definition.id is None else MANAGED_EDIT_MESSAGE
    if definition.id is not None and _stored_test_type(definition.id) in MANAGED_TEST_TYPES:
        return MANAGED_EDIT_MESSAGE
    tables = writable_tables(suite)
    if (
        tables is not None
        and definition.table_name not in tables
        and (definition.id is None or definition.table_name != _stored_table_name(definition.id))
    ):
        if not definition.table_name:
            return "A test on a contract must name one of the tables the contract declares."
        return (
            f"The contract does not declare the table {definition.table_name}. Add it under Declared Tables on "
            "the Contract Metadata tab, or choose a declared table."
        )
    if definition.test_type not in NON_PUBLIC_TEST_TYPES:
        test_type = TestType.get(definition.test_type)
        # The dialog neither shows these fields nor lets the user clear them, so a stored value in
        # one would fail validation with no way to fix it from the form.
        if test_type.test_scope not in COLUMN_NAME_SCOPES:
            definition.column_name = None
        if "custom_query" not in test_type.param_columns:
            definition.custom_query = None
        try:
            definition.validate(test_type)
        except InvalidTestDefinitionFields as error:
            return _describe_errors(error.errors, test_type)
    definition.save()
    return None


def _describe_errors(errors: dict[str, str], test_type: TestType) -> str:
    labels = {column: prompt for column, prompt, _ in test_type.param_fields}
    labels["column_name"] = test_type.column_name_prompt or "Column"
    details = "; ".join(
        f"{labels.get(field) or field.replace('_', ' ').capitalize()}: {reason}" for field, reason in errors.items()
    )
    return f"The test could not be saved. {details.replace('`', '')}."


def dialog_table_columns(
    suite: TestSuite | TestSuiteMinimal, table_columns: list[dict], current_table: str | None = None
) -> list[dict]:
    """The catalog columns the Add Test and Edit Test dialogs offer: on a contract, those of the tables it
    declares, and of ``current_table``, the table of the test being edited."""
    tables = writable_tables(suite)
    if tables is None:
        return table_columns
    offered = {*tables, current_table}
    return [column for column in table_columns if column["table_name"] in offered]


def _stored_test_type(test_definition_id: object) -> str | None:
    return get_current_session().scalar(
        select(TestDefinition.test_type).where(TestDefinition.id == test_definition_id)
    )


def _stored_table_name(test_definition_id: object) -> str | None:
    return get_current_session().scalar(
        select(TestDefinition.table_name).where(TestDefinition.id == test_definition_id)
    )
