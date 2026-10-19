from testgen.common.models.test_definition import (
    COLUMN_NAME_SCOPES,
    NON_PUBLIC_TEST_TYPES,
    InvalidTestDefinitionFields,
    TestDefinition,
    TestType,
)


def save_from_dialog(definition: TestDefinition) -> str | None:
    """Validate and save a test definition built from the Add Test or Edit Test dialog.

    Returns a message naming each invalid field, without saving, when validation fails; None once saved.
    """
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
