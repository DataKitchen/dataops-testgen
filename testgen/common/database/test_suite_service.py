"""Shared test-suite helpers — common-layer logic shared by the API, MCP and the UI.

* ``validate_test_suite_fields`` — required-field, width and value checks. Callers
  surface the returned messages verbatim.
"""

from __future__ import annotations

from collections.abc import Mapping

from testgen.common.generation_set_service import resolve_generation_sets
from testgen.common.models.test_suite import SuiteSeverity, TestSuite

# Widths of the ``test_suites`` VARCHAR columns (030_initialize_new_schema_structure.sql).
_MAX_LENGTHS: dict[str, int] = {
    "test_suite": 200,
    "test_suite_description": 1000,
    "component_key": 100,
    "component_type": 100,
    "component_name": 100,
}

_PUBLIC_FIELD_NAMES: dict[str, str] = {
    "test_suite": "test_suite_name",
    "test_suite_description": "description",
    "severity": "default_severity",
    "dq_score_exclude": "exclude_from_quality_score",
}


def validate_test_suite_fields(
    test_suite: TestSuite,
    *,
    field_names: Mapping[str, str] | None = None,
    quote_fields: bool = True,
) -> list[str]:
    """Return every validation error (empty list = valid).

    ``generation_sets`` is checked only when set, against the sets the database defines.

    Args:
        test_suite: The test suite to check.
        field_names: Name to show for a model attribute in the messages, keyed by
            attribute. Overrides the public field names, which the messages use by
            default; an attribute with no public name is shown by its own name.
        quote_fields: Whether to wrap field names in backticks.
    """
    names = {**_PUBLIC_FIELD_NAMES, **(field_names or {})}

    def field(attr: str) -> str:
        name = names.get(attr, attr)
        return f"`{name}`" if quote_fields else name

    errors: list[str] = []

    name = test_suite.test_suite
    if name is None or not name.strip():
        errors.append(f"{field('test_suite')} is required.")

    for attr, max_length in _MAX_LENGTHS.items():
        value = getattr(test_suite, attr)
        if isinstance(value, str) and len(value) > max_length:
            errors.append(f"{field(attr)} must be at most {max_length} characters.")

    severity = test_suite.severity
    if severity is not None and severity not in set(SuiteSeverity):
        valid = ", ".join(member.value for member in SuiteSeverity)
        errors.append(f"{field('severity')} must be one of {valid}.")

    if test_suite.generation_sets is not None:
        try:
            resolve_generation_sets(test_suite, test_suite.generation_sets)
        except (TypeError, ValueError) as err:
            errors.append(f"{field('generation_sets')}: {err}")

    return errors
