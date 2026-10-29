import pytest

from testgen.common.source_value_fields import hidden_slots, value_digest

pytestmark = pytest.mark.unit


def test_hidden_slots_find_every_field_that_can_carry_source_values():
    document = {
        "schema": [{
            "name": "orders",
            "quality": [{"metric": "rowCount", "mustBeGreaterThan": 100}],
            "properties": [{
                "name": "amount",
                "examples": [42.0],
                "enum": [{"value": 42.0}],
                "logicalTypeOptions": {"minimum": 0.5, "maxLength": 8},
                "customProperties": [{"property": "profiledValues", "value": {"maximum": 120, "minLength": 2}}],
                "quality": [{
                    "metric": "nullValues",
                    "customProperties": [{"vendor": "testgen", "property": "thresholdBound", "value": 5}],
                }],
            }],
        }],
    }

    paths = {slot.path for slot in hidden_slots(document)}

    assert paths == {
        "$.schema[0].quality[0].mustBeGreaterThan",
        "$.schema[0].properties[0].examples",
        "$.schema[0].properties[0].enum",
        "$.schema[0].properties[0].logicalTypeOptions.minimum",
        "$.schema[0].properties[0].customProperties[0].value.maximum",
        "$.schema[0].properties[0].quality[0].customProperties[0].value",
    }


def test_a_quality_rules_query_is_not_a_hidden_slot():
    document = {"schema": [{"name": "orders", "quality": [{"type": "sql", "query": "SELECT 1"}]}]}

    assert list(hidden_slots(document)) == []


def test_value_digest_is_stable_and_keyed():
    assert value_digest(b"a" * 32, "", [1, 2]) == value_digest(b"a" * 32, "", [1, 2])
    assert value_digest(b"a" * 32, "", [1, 2]) != value_digest(b"b" * 32, "", [1, 2])
    assert value_digest(b"a" * 32, "", [1, 2]) != value_digest(b"a" * 32, "", [1, 3])
