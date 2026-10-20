from unittest.mock import patch

import pytest

from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.ui.services.test_definition_service import save_from_dialog

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


def _save(definition: TestDefinition, test_type: TestType) -> tuple[str | None, bool]:
    with (
        patch(f"{SERVICE_MODULE}.TestType.get", return_value=test_type),
        patch.object(TestDefinition, "save") as save,
    ):
        error = save_from_dialog(definition)
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
        assert save_from_dialog(definition) is None

    get_test_type.assert_not_called()
    save.assert_called_once()
    assert definition.custom_query == "SELECT COUNT(*)"
