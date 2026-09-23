"""Settling the reference schema on a flavor that reaches every table through one schema."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from testgen.common.database.table_group_service import apply_test_definition_flavor_rules
from testgen.common.models.test_definition import TestDefinition

pytestmark = pytest.mark.unit


def _table_group(schema="main"):
    table_group = MagicMock()
    table_group.id = uuid4()
    table_group.table_group_schema = schema
    return table_group


def test_a_flavor_with_one_schema_has_the_reference_schema_written_for_it():
    definition = TestDefinition(schema_name="main", match_table_name="customers")

    apply_test_definition_flavor_rules(definition, _table_group(), qualifies_table_refs=False)

    assert definition.match_schema_name == "main"


def test_a_schema_carried_in_from_elsewhere_is_replaced():
    """An import or a copy brings the source's schema, which names nothing on the target."""
    definition = TestDefinition(
        schema_name="main", match_table_name="customers", match_schema_name="public"
    )

    apply_test_definition_flavor_rules(definition, _table_group(), qualifies_table_refs=False)

    assert definition.match_schema_name == "main"


def test_a_flavor_that_qualifies_keeps_what_the_caller_supplied():
    definition = TestDefinition(
        schema_name="sales", match_table_name="customers", match_schema_name="reference"
    )

    apply_test_definition_flavor_rules(definition, _table_group("sales"), qualifies_table_refs=True)

    assert definition.match_schema_name == "reference"


def test_a_flavor_that_qualifies_still_fills_a_blank():
    """The reference schema is required, and the form is the only thing asking for it."""
    definition = TestDefinition(schema_name="sales", match_table_name="customers")

    apply_test_definition_flavor_rules(definition, _table_group("sales"), qualifies_table_refs=True)

    assert definition.match_schema_name == "sales"


@pytest.mark.parametrize("qualifies", [True, False])
def test_a_definition_with_no_reference_table_is_left_alone(qualifies):
    definition = TestDefinition(schema_name="main")

    apply_test_definition_flavor_rules(definition, _table_group(), qualifies_table_refs=qualifies)

    assert definition.match_schema_name is None
